"""PoolObject and PoolModel: what the integration keeps and how it updates."""

from custom_components.intellicenter.pyintellicenter import PoolModel, PoolObject

from helpers import pruned, real_attributes_map


def test_undefined_attribute_reads_as_none():
    obj = PoolObject("SCH01", {"OBJTYP": "SCHED", "SNAME": "Sched"})
    assert obj["ACT"] is None
    assert obj.sname == "Sched"


def test_object_without_a_type_is_skipped_not_fatal():
    model = PoolModel({"BODY": {"SNAME"}})
    model.addObjects([
        {"objnam": "X", "params": {"SNAME": "no type"}},
        {"objnam": "B1", "params": {"OBJTYP": "BODY", "SNAME": "Pool"}},
    ])
    # one malformed entry used to abort the whole model load from start()
    assert model["X"] is None
    assert model["B1"] is not None


def test_only_mapped_object_types_are_kept():
    model = PoolModel({"BODY": {"SNAME"}})
    model.addObjects([
        {"objnam": "B1", "params": {"OBJTYP": "BODY", "SNAME": "Pool"}},
        {"objnam": "P1", "params": {"OBJTYP": "PUMP", "SNAME": "Pump"}},
    ])
    assert model["B1"] is not None
    assert model["P1"] is None, "an unmapped type is dropped silently"


def test_every_type_the_platforms_need_is_mapped():
    """The map is an allow-list; a missing type means a dead platform."""
    mapped = real_attributes_map()
    for objtype in ("BODY", "CIRCUIT", "CIRCGRP", "CHEM", "HEATER", "PUMP",
                    "SENSE", "SCHED", "SYSTEM", "EXTINSTR"):
        assert objtype in mapped, f"{objtype} objects would be discarded"


def test_tracked_attributes_cover_what_entities_read():
    from custom_components.intellicenter.pyintellicenter.attributes import (
        ALL_ATTRIBUTES_BY_TYPE,
    )
    mapped = real_attributes_map()

    def tracked(objtype):
        attrs = mapped.get(objtype)
        if not attrs:  # an empty set falls back to the library's full list
            attrs = ALL_ATTRIBUTES_BY_TYPE.get(objtype) or set()
        return set(attrs)

    needs = {
        "BODY": {"SNAME", "STATUS", "HEATER", "HTMODE", "LOTMP", "LSTTMP", "VOL"},
        "CIRCUIT": {"SNAME", "STATUS", "USE", "FEATR"},
        "CIRCGRP": {"CIRCUIT"},
        "SCHED": {"SNAME", "ACT", "VACFLO"},
        "PUMP": {"SNAME", "STATUS", "PWR", "RPM", "GPM"},
        "HEATER": {"SNAME", "BODY", "LISTORD"},
        "SENSE": {"SNAME", "SOURCE"},
        "SYSTEM": {"VACFLO"},
        "EXTINSTR": {"STATUS", "NORMAL"},
        "CHEM": {"PRIM", "SEC", "SUPER", "SALT", "BODY"},
    }
    for objtype, attrs in needs.items():
        missing = attrs - tracked(objtype)
        assert not missing, f"{objtype} entities read untracked {sorted(missing)}"


def test_update_reports_only_what_changed():
    model = PoolModel({"BODY": {"STATUS"}})
    model.addObjects([{"objnam": "B1", "params": {"OBJTYP": "BODY", "STATUS": "ON"}}])
    assert model.processUpdates([{"objnam": "B1", "params": {"STATUS": "ON"}}]) == {}
    assert model.processUpdates(
        [{"objnam": "B1", "params": {"STATUS": "OFF"}}]) == {"B1": {"STATUS": "OFF"}}


def test_update_for_an_unknown_object_is_ignored():
    model = PoolModel({"BODY": {"STATUS"}})
    assert model.processUpdates([{"objnam": "ZZZ", "params": {"STATUS": "ON"}}]) == {}


def test_reloading_does_not_replace_existing_objects():
    model = PoolModel(real_attributes_map())
    model.addObjects(pruned())
    first = model["B1101"]
    model.addObjects(pruned())
    assert model["B1101"] is first, "reconnecting must not orphan entity references"


def test_lookups_by_type_and_parent():
    model = PoolModel(real_attributes_map())
    model.addObjects(pruned())
    assert {o.objnam for o in model.getByType("BODY")} == {"B1101", "B1202"}
    assert [o.objnam for o in model.getByType("BODY", "SPA")] == ["B1202"]
    assert model.getByType("NOPE") == []


def test_pump_uses_numeric_on_off_statuses():
    pump = PoolObject("P1", {"OBJTYP": "PUMP"})
    body = PoolObject("B1", {"OBJTYP": "BODY"})
    assert (pump.onStatus, pump.offStatus) == ("10", "4")
    assert (body.onStatus, body.offStatus) == ("ON", "OFF")


def test_light_classification():
    def circuit(subtype):
        return PoolObject("C1", {"OBJTYP": "CIRCUIT", "SUBTYP": subtype})

    assert circuit("INTELLI").isALight and circuit("INTELLI").supportColorEffects
    assert circuit("GLOW").supportColorEffects
    assert circuit("LIGHT").isALight and not circuit("LIGHT").supportColorEffects
    assert circuit("LITSHO").isALightShow and not circuit("LITSHO").isALight
    assert not circuit("GENERIC").isALight

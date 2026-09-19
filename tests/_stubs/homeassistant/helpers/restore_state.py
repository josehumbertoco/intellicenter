
class RestoreEntity:
    _restored = None

    async def async_get_last_state(self):
        return self._restored

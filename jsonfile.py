import asyncio
import json
import os
import uuid


class File(dict):
    def __init__(self, path):
        self.path = path
        self.loop = asyncio.get_event_loop()
        self.lock = asyncio.Lock()
        super().__init__(self.load())

    def load(self):
        try:
            with open(self.path, 'r') as file:
                return json.load(file)
        except FileNotFoundError:
            return {}

    def write(self):
        temp = f'{uuid.uuid4()}.tmp'
        with open(temp, 'w', encoding='utf-8') as tmp:
            json.dump(self.copy(), tmp, ensure_ascii=True, separators=(',', ':'))
        os.replace(temp, self.path)

    async def save(self):
        async with self.lock:
            await self.loop.run_in_executor(None, self.write)
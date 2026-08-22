import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import config
import db.database as db
from services.settlement import _config_shares
from services.splits import (
    clear_category_config,
    clear_global_config,
    create_config,
    resolve_config,
    set_category_config,
    set_global_config,
    validate_percentages,
    validate_weights,
)


class SplitConfigTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = TemporaryDirectory()
        config.DB_PATH = Path(self.tmp.name) / "roommates.db"
        await db.close()
        await db.init_schema()
        self.guild_id = 123
        await db.ensure_guild(self.guild_id)
        self.member_ids = [
            await db.ensure_member(self.guild_id, 1, "Alex"),
            await db.ensure_member(self.guild_id, 2, "Sam"),
            await db.ensure_member(self.guild_id, 3, "Lee"),
        ]
        conn = await db.connect()
        await conn.execute(
            "INSERT INTO categories (guild_id, name, created_by) VALUES (?, ?, ?)",
            (self.guild_id, "Groceries", self.member_ids[0]),
        )
        await conn.commit()
        cursor = await conn.execute(
            "SELECT id FROM categories WHERE guild_id = ? AND name = ?",
            (self.guild_id, "Groceries"),
        )
        self.category_id = (await cursor.fetchone())["id"]

    async def asyncTearDown(self):
        await db.close()
        self.tmp.cleanup()

    async def test_resolution_priority_and_fallback(self):
        global_config_id = await create_config(
            self.guild_id,
            self.member_ids[0],
            "percent",
            {
                self.member_ids[0]: 50,
                self.member_ids[1]: 30,
                self.member_ids[2]: 20,
            },
        )
        await set_global_config(self.guild_id, global_config_id)

        category_config_id = await create_config(
            self.guild_id,
            self.member_ids[0],
            "weight",
            {
                self.member_ids[0]: 2,
                self.member_ids[1]: 1,
                self.member_ids[2]: 1,
            },
        )
        await set_category_config(self.guild_id, self.category_id, category_config_id)

        resolved_for_category = await resolve_config(self.guild_id, self.category_id)
        self.assertIsNotNone(resolved_for_category)
        self.assertEqual(resolved_for_category["id"], category_config_id)

        resolved_unknown_category = await resolve_config(self.guild_id, 999999)
        self.assertIsNotNone(resolved_unknown_category)
        self.assertEqual(resolved_unknown_category["id"], global_config_id)

        await clear_category_config(self.guild_id, self.category_id)
        resolved_after_category_clear = await resolve_config(self.guild_id, self.category_id)
        self.assertIsNotNone(resolved_after_category_clear)
        self.assertEqual(resolved_after_category_clear["id"], global_config_id)

        await clear_global_config(self.guild_id)
        resolved_without_any = await resolve_config(self.guild_id, self.category_id)
        self.assertIsNone(resolved_without_any)

    async def test_weight_normalization(self):
        config_id = await create_config(
            self.guild_id,
            self.member_ids[0],
            "weight",
            {
                self.member_ids[0]: 2,
                self.member_ids[1]: 1,
                self.member_ids[2]: 1,
            },
        )
        shares = await _config_shares(config_id, 101, self.member_ids)
        self.assertEqual(sum(shares.values()), 101)
        self.assertEqual(shares[self.member_ids[0]], 51)
        self.assertEqual(shares[self.member_ids[1]], 25)
        self.assertEqual(shares[self.member_ids[2]], 25)

    def test_percentage_validation(self):
        self.assertIsNone(validate_percentages([33.333, 33.333, 33.334]))
        self.assertIsNotNone(validate_percentages([50, 40]))
        self.assertIsNotNone(validate_percentages([50, -50, 100]))

    def test_weight_validation(self):
        self.assertIsNone(validate_weights([2, 1, 1]))
        self.assertIsNotNone(validate_weights([2, 0, 1]))


if __name__ == "__main__":
    unittest.main()

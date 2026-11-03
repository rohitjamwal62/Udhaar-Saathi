from apps.common.db import q1
from apps.common.errors import ApiProblem


def shop_for_user(user_id: str, shop_id: str | None = None) -> dict:
    """The caller's shop (owner or active member). Raises 404 for anything else, so one tenant
    can never learn whether another tenant's ids exist."""
    sql = """SELECT s.* FROM shops s
              WHERE (s.owner_user_id = %s
                     OR EXISTS (SELECT 1 FROM shop_members m
                                 WHERE m.shop_id = s.id AND m.user_id = %s AND m.status = 'active'))"""
    params: list = [user_id, user_id]
    if shop_id:
        sql += " AND s.id = %s"
        params.append(str(shop_id))
    row = q1(sql + " ORDER BY s.created_at LIMIT 1", params)
    if not row:
        raise ApiProblem("Shop not found.", "not_found", 404)
    return row

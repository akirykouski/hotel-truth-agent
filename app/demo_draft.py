"""Демо-черновик для жюри: в registry/custom/ лежит готовый черновик с отчётом (demo_seed: true), а его факты
дорасчитываются в рабочую базу при старте, если их там нет. Бинарный предрасчёт data/facts.sqlite не меняется,
после удаления рабочей базы или свежего клона всё восстанавливается само (шаблонный рецепт, около секунды)."""
from app import registry, store


def ensure():
    ids = [cid for cid, s in registry.all_chars().items() if s.get("demo_seed")]
    for cid in ids:
        have = store.conn().execute("SELECT COUNT(*) FROM facts WHERE char_id=?", (cid,)).fetchone()[0]
        if not have:
            registry.compute_all([cid])
    return ids

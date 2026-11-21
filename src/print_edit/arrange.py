"""並べ方（まとめ方・1名刺あたりの枚数・並べ順）からスロット割当を作る。描画は core/layout.py に任せ、ここは割当だけを決める。"""
from __future__ import annotations


def fill_qty(n_cards: int, capacity: int) -> int:
    """「全部埋める」の1名刺あたりの枚数。均等に割り、名刺数が容量を超えるときは各1枚。"""
    if n_cards <= 0:
        return 0
    return max(1, capacity // n_cards)


def slot_order(capacity: int, columns: int, order: str) -> list[int]:
    """スロットへ置く順の 0 始まり番号。row=行優先 / col=列優先（上から下へ、容量を超える番号は飛ばす）。"""
    if order != "col":
        return list(range(capacity))
    rows = -(-capacity // columns)
    return [r * columns + c for c in range(columns) for r in range(rows) if r * columns + c < capacity]


def assign(seq: list[int], columns: int, capacity: int, order: str) -> list[int | None]:
    """seq（名刺 id を枚数ぶん並べた列。容量以内）を、長さ capacity のスロット列（空は None）に割り当てる。"""
    slots: list[int | None] = [None] * capacity
    for idx, cid in zip(slot_order(capacity, columns, order), seq[:capacity]):
        slots[idx] = cid
    return slots


def trim(slots: list[int | None]) -> list[int | None]:
    """末尾の空スロットを落とす。"""
    n = len(slots)
    while n and slots[n - 1] is None:
        n -= 1
    return slots[:n]


def plan_sheets(card_ids: list[int], group: str, per_card: int | None, order: str, columns: int, capacity: int) -> list[list[int | None]]:
    """取込&作成: card_ids（取り込み順）から PDF ごとのスロット列を作る。

    multi: 名刺を枚数ぶん並べた列を容量ごとに区切り、超過分は順序を保って次の PDF の先頭から詰める。
    single: 名刺ごとに別の PDF。1名刺の枚数が容量を超えるときはその名刺の PDF を続けて作る。
    """
    if not card_ids:
        return []
    out: list[list[int | None]] = []
    if group == "single":
        qty = per_card if per_card is not None else capacity
        for cid in card_ids:
            seq = [cid] * qty
            for k in range(0, len(seq), capacity):
                out.append(trim(assign(seq[k : k + capacity], columns, capacity, order)))
        return out
    qty = per_card if per_card is not None else fill_qty(len(card_ids), capacity)
    seq = [cid for cid in card_ids for _ in range(qty)]
    for k in range(0, len(seq), capacity):
        out.append(trim(assign(seq[k : k + capacity], columns, capacity, order)))
    return out


def fill_count(n_cards: int, capacity: int) -> int:
    return fill_qty(n_cards, capacity)


def auto_slots(seq: list[int], capacity: int, columns: int, order: str) -> dict[int, int]:
    """seq を並べ順どおりに置いた {1 始まりのスロット番号: 名刺 id}。"""
    return {i + 1: cid for i, cid in enumerate(assign(seq, columns, capacity, order)) if cid is not None}

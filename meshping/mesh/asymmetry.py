from __future__ import annotations

from dataclasses import dataclass

from meshping.mesh.matrix import MatrixStore


@dataclass(frozen=True)
class AsymmetryFinding:
    source_id: str
    target_id: str
    forward_ms: float
    reverse_ms: float
    ratio: float


def detect_asymmetries(
    matrix: MatrixStore,
    *,
    threshold: float = 2.0,
) -> list[AsymmetryFinding]:
    findings: list[AsymmetryFinding] = []
    visited: set[frozenset[str]] = set()

    for cell in matrix.iter_cells():
        cell.asymmetric = False
        cell.asymmetry_ratio = None

    for cell in matrix.iter_cells():
        if cell.source_id == cell.target_id or cell.p50 is None or cell.p50 <= 0:
            continue
        pair_key = frozenset((cell.source_id, cell.target_id))
        if pair_key in visited:
            continue
        reverse = matrix.get(cell.target_id, cell.source_id)
        if not reverse or reverse.p50 is None or reverse.p50 <= 0:
            continue
        ratio = max(cell.p50, reverse.p50) / min(cell.p50, reverse.p50)
        if ratio <= threshold:
            continue
        visited.add(pair_key)
        cell.asymmetric = True
        reverse.asymmetric = True
        cell.asymmetry_ratio = ratio
        reverse.asymmetry_ratio = ratio
        findings.append(
            AsymmetryFinding(
                source_id=cell.source_id,
                target_id=cell.target_id,
                forward_ms=cell.p50,
                reverse_ms=reverse.p50,
                ratio=ratio,
            )
        )

    return findings

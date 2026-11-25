"""Supplier registry service managing supplier reliability scores, performance metrics, and tiers."""
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("restartai.supplier_registry")


class SupplierRegistryService:
    def __init__(self, registry_path: Optional[Path] = None):
        self.registry_path = registry_path or (
            Path(__file__).resolve().parent.parent.parent / "data" / "supplier_registry.json"
        )
        self._data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if not self.registry_path.exists():
            return {"suppliers": []}
        try:
            return json.loads(self.registry_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("Failed to load supplier registry from %s: %s", self.registry_path, exc)
            return {"suppliers": []}

    def _save(self) -> None:
        try:
            self.registry_path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.error("Failed to save supplier registry to %s: %s", self.registry_path, exc)

    def list_suppliers(self) -> List[Dict[str, Any]]:
        return self._data.get("suppliers", [])

    def get_supplier(self, name: str) -> Optional[Dict[str, Any]]:
        clean = name.strip().lower()
        for s in self.list_suppliers():
            if s["name"].lower() == clean:
                return s
        return None

    def get_reliability_score(self, name: str) -> float:
        s = self.get_supplier(name)
        return float(s.get("reliability_score", 0.90)) if s else 0.85

    def update_supplier_reliability(self, name: str, score: float) -> Optional[Dict[str, Any]]:
        score = max(0.1, min(1.0, float(score)))
        for s in self._data.get("suppliers", []):
            if s["name"].lower() == name.strip().lower():
                s["reliability_score"] = round(score, 2)
                self._save()
                return s
        # If supplier does not exist yet, add it
        new_entry = {
            "name": name.strip(),
            "reliability_score": round(score, 2),
            "fulfillment_rate": round(score, 2),
            "tier": "Custom Supplier",
        }
        self._data.setdefault("suppliers", []).append(new_entry)
        self._save()
        return new_entry

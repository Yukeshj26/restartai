"""Asset Registry service managing machines, critical parts, specifications, and telemetry triggers."""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..models import RecoveryRequest, Supplier

logger = logging.getLogger("restartai.assets")


class AssetService:
    def __init__(self, assets_path: Optional[Path] = None):
        self.assets_path = assets_path or (
            Path(__file__).resolve().parent.parent.parent / "data" / "assets.json"
        )
        self._data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if not self.assets_path.exists():
            logger.warning("Asset registry file not found at %s", self.assets_path)
            return {"machines": []}
        try:
            return json.loads(self.assets_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error(
                "Failed to parse asset registry at %s: %s", self.assets_path, exc
            )
            return {"machines": []}

    def list_machines(self) -> List[Dict[str, Any]]:
        """Returns all configured factory machines in the registry."""
        return self._data.get("machines", [])

    def get_machine(self, identifier: str) -> Optional[Dict[str, Any]]:
        """Finds a machine by ID or case-insensitive name match."""
        identifier_clean = identifier.strip().lower()
        for machine in self.list_machines():
            if (
                machine["id"].lower() == identifier_clean
                or machine["name"].lower() == identifier_clean
            ):
                return machine
            # Partial name match
            if identifier_clean in machine["name"].lower():
                return machine
        return None

    def get_primary_part(self, machine_id: str) -> Optional[Dict[str, Any]]:
        """Gets primary replacement part configuration for a machine."""
        machine = self.get_machine(machine_id)
        if not machine or not machine.get("parts"):
            return None
        parts = machine["parts"]
        return next((p for p in parts if p.get("is_primary")), parts[0])

    def get_part_equivalents(self, part_number: str) -> List[Dict[str, Any]]:
        """Searches across all registered parts for equivalent brands/models."""
        part_clean = part_number.strip().lower()
        for machine in self.list_machines():
            for p in machine.get("parts", []):
                if (
                    p["part_number"].lower() == part_clean
                    or part_clean in p["part_number"].lower()
                ):
                    return p.get("equivalents", [])
                for eq in p.get("equivalents", []):
                    if eq["part_number"].lower() == part_clean:
                        # Return siblings + primary
                        return [
                            {
                                "brand": "Original OEM",
                                "part_number": p["part_number"],
                                "compatibility_confidence": 1.0,
                                "notes": "OEM baseline",
                            }
                        ] + [
                            e
                            for e in p.get("equivalents", [])
                            if e["part_number"].lower() != part_clean
                        ]
        return []

    def build_recovery_request(
        self,
        machine_id: str = "cnc-line-4",
        overrides: Optional[Dict[str, Any]] = None,
    ) -> RecoveryRequest:
        """Formulates a validated RecoveryRequest from the machine asset definition."""
        machine = self.get_machine(machine_id)
        if not machine:
            # Fallback to default CNC Line 4 parameters
            logger.warning(
                "Machine '%s' not found in registry. Using default golden parameters.",
                machine_id,
            )
            machine = {
                "name": "CNC Production Line 4",
                "downtime_cost_per_hour": 5000.0,
                "default_max_recovery_hours": 3.0,
                "default_technicians": 3,
                "default_suppliers": [
                    {"name": "Supplier A", "phone": "+919876543211"},
                    {"name": "Supplier B", "phone": "+919876543212"},
                    {"name": "Supplier C", "phone": "+919876543213"},
                    {"name": "Supplier D", "phone": "+919876543214"},
                ],
                "parts": [
                    {
                        "part_number": "SKF 6205-2RS",
                        "part_description": "Deep-groove ball bearing",
                        "default_quantity": 20,
                        "compatibility_notes": "6205-2RS",
                    }
                ],
            }

        part = (machine.get("parts") or [{}])[0]
        supp_data = machine.get("default_suppliers") or [
            {"name": "Supplier A", "phone": "+919876543211"},
            {"name": "Supplier B", "phone": "+919876543212"},
            {"name": "Supplier C", "phone": "+919876543213"},
            {"name": "Supplier D", "phone": "+919876543214"},
        ]
        suppliers = [Supplier(**s) for s in supp_data]

        params = {
            "mode": "demo",
            "machine": machine["name"],
            "part_number": part.get("part_number", "SKF 6205-2RS"),
            "part_description": part.get(
                "part_description", "Deep-groove ball bearing"
            ),
            "quantity": part.get("default_quantity", 20),
            "max_hours": float(machine.get("default_max_recovery_hours", 3.0)),
            "downtime_cost_per_hour": float(
                machine.get("downtime_cost_per_hour", 5000.0)
            ),
            "compatibility_notes": part.get("compatibility_notes", ""),
            "available_technicians": int(machine.get("default_technicians", 3)),
            "suppliers": suppliers,
            "live_confirmed": False,
        }

        if overrides:
            params.update({k: v for k, v in overrides.items() if v is not None})

        return RecoveryRequest(**params)

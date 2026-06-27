from __future__ import annotations


def paper_telemetry_to_calibration_study(telemetry: dict[str, object]) -> dict[str, object]:
    return {
        "action": "RequestCalibrationStudy",
        "source": "paper_telemetry",
        "direct_policy_mutation": False,
        "telemetry": dict(telemetry),
    }

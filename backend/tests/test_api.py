import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure backend root directory is on sys.path for direct test execution
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from fastapi.testclient import TestClient
import main


class TestSafeSnapTriageAPI(unittest.TestCase):
    """Automated test suite verifying critical SafeSnap Triage API flows."""

    def setUp(self):
        """Set up FastAPI test client for each test case."""
        self.client = TestClient(main.app)

    # -------------------------------------------------------------------------
    # Flow A: Health Test
    # -------------------------------------------------------------------------
    def test_health_check(self):
        """Verify GET /api/health returns 200 with status 'ok'."""
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("status", data)
        self.assertEqual(data["status"], "ok")

    # -------------------------------------------------------------------------
    # Flow B: Valid Analyze Test (Text Input)
    # -------------------------------------------------------------------------
    def test_analyze_valid_text(self):
        """Verify POST /api/analyze with valid text returns 200 and expected schema."""
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "hazard_identified": "Heat Exhaustion / Dizziness",
            "severity_level": "Medium",
            "immediate_steps": [
                "Sit or lie down in a shaded area.",
                "Drink small sips of cool water.",
                "Alert nearby staff or medical services."
            ]
        })

        with patch.dict(os.environ, {"GEMINI_API_KEY": "mock_test_key_not_real"}):
            with patch.object(main.model, "generate_content", return_value=mock_response):
                response = self.client.post("/api/analyze", data={"text": "Dizziness and fatigue"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("hazard_identified", data)
        self.assertIn("severity_level", data)
        self.assertIn("immediate_steps", data)
        self.assertEqual(data["hazard_identified"], "Heat Exhaustion / Dizziness")
        self.assertEqual(data["severity_level"], "Medium")
        self.assertEqual(len(data["immediate_steps"]), 3)

    # -------------------------------------------------------------------------
    # Flow B (cont.): Valid Analyze Test (Image Upload)
    # -------------------------------------------------------------------------
    def test_analyze_valid_image(self):
        """Verify POST /api/analyze with a valid image upload returns 200."""
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "hazard_identified": "Liquid Chemical Spill",
            "severity_level": "High",
            "immediate_steps": [
                "Evacuate immediate spill zone.",
                "Caution others in the hallway.",
                "Contact campus security dispatch."
            ]
        })

        # Valid JPEG magic header bytes (\xff\xd8)
        valid_jpeg_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF" + (b"\x00" * 100)

        with patch.dict(os.environ, {"GEMINI_API_KEY": "mock_test_key_not_real"}):
            with patch.object(main.model, "generate_content", return_value=mock_response):
                response = self.client.post(
                    "/api/analyze",
                    files={"image": ("scene.jpg", valid_jpeg_bytes, "image/jpeg")}
                )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["hazard_identified"], "Liquid Chemical Spill")
        self.assertEqual(data["severity_level"], "High")
        self.assertEqual(len(data["immediate_steps"]), 3)

    # -------------------------------------------------------------------------
    # Flow C: Invalid Input Test
    # -------------------------------------------------------------------------
    def test_analyze_invalid_file_type(self):
        """Verify uploading a non-image file type returns HTTP 400."""
        text_file_bytes = b"This is a text document, not an image."
        response = self.client.post(
            "/api/analyze",
            files={"image": ("report.txt", text_file_bytes, "text/plain")}
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn("detail", data)
        self.assertIn("Invalid file type", data["detail"])

    # -------------------------------------------------------------------------
    # Flow D: Empty/Missing Input Test
    # -------------------------------------------------------------------------
    def test_analyze_missing_input(self):
        """Verify submitting empty input (no text, no image) returns HTTP 400."""
        response = self.client.post("/api/analyze", data={})
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn("detail", data)
        self.assertIn("Must provide either an image or text input", data["detail"])

    # -------------------------------------------------------------------------
    # Flow E: AI Service Failure Test
    # -------------------------------------------------------------------------
    def test_analyze_ai_service_failure(self):
        """Verify upstream AI exception is handled safely with HTTP 500."""
        with patch.dict(os.environ, {"GEMINI_API_KEY": "mock_test_key_not_real"}):
            with patch.object(
                main.model,
                "generate_content",
                side_effect=RuntimeError("Upstream service timeout")
            ):
                response = self.client.post(
                    "/api/analyze",
                    data={"text": "Person bleeding from forearm"}
                )

        self.assertEqual(response.status_code, 500)
        data = response.json()
        self.assertIn("detail", data)
        self.assertIn("AI analysis failed", data["detail"])

    # -------------------------------------------------------------------------
    # Flow F: Image Upload Edge Case (Corrupted Header)
    # -------------------------------------------------------------------------
    def test_analyze_corrupted_image_header(self):
        """Verify image with invalid magic bytes header is rejected with HTTP 400."""
        corrupted_bytes = b"NOT_A_VALID_MAGIC_HEADER_BYTES"
        response = self.client.post(
            "/api/analyze",
            files={"image": ("fake.jpg", corrupted_bytes, "image/jpeg")}
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn("detail", data)
        self.assertIn("Corrupted or unrecognized image format", data["detail"])


if __name__ == "__main__":
    unittest.main()

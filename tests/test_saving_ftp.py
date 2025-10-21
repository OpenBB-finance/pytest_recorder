"""Tests for recording FTP interactions using pytest-recorder."""

import io
import ftplib
import urllib.request

import pytest

FTP_HOST = "ftp.nasdaqtrader.com"
FTP_DIR = "/symboldirectory"
FTP_FILE = "bondslist.txt"


class TestFTPRecording:
    @pytest.mark.record_ftp
    def test_download_via_urlopen(self):
        """Tests recording of urllib `urlopen` with an FTP URL."""
        url = f"ftp://{FTP_HOST}{FTP_DIR}/{FTP_FILE}"
        with urllib.request.urlopen(url) as response:
            data = response.read().decode("utf-8")
        assert "Symbol|Security Name" in data

    @pytest.mark.record_ftp
    def test_download_via_ftplib(self):
        """Tests recording of ftplib `retrbinary`."""
        ftp = ftplib.FTP(FTP_HOST)
        ftp.login()
        ftp.cwd(FTP_DIR)
        bio = io.BytesIO()
        ftp.retrbinary(f"RETR {FTP_FILE}", bio.write)
        data = bio.getvalue()
        ftp.quit()
        assert b"Symbol|Security Name" in data

    @pytest.mark.record_ftp
    def test_upload_via_ftplib(self):
        """Tests recording of ftplib commands that result in a permanent error."""
        ftp = ftplib.FTP("ftp.dlptest.com")
        # test FTP server that allows uploads with test user
        ftp.login("dlpuser", "rNrKYTX9g7z3RgJRmxWuGHbeu")  # pragma: allowlist secret
        bio = io.BytesIO(b"pytest-recorder-test")
        ftp.storbinary("STOR upload_test.dlp", bio)
        ftp.quit()


class TestFTPFilterArgs:
    @pytest.fixture(name="vcr_config")
    def vcr_config_fixture(self):
        return {"filter_arguments": [("symboldirectory", "censored_dir")]}

    @pytest.mark.record_ftp
    def test_filter_arguments(self, vcr_config):
        """Test that filter_arguments correctly censors request arguments."""
        _ = vcr_config
        ftp = ftplib.FTP(FTP_HOST)
        ftp.login()
        ftp.cwd(FTP_DIR)
        ftp.quit()


class TestFTPFilterBody:
    def _censor_body(self, response):
        response["body"]["string"] = "censored"
        return response

    @pytest.fixture(name="vcr_config")
    def vcr_config_fixture(self):
        return {"before_record_response": [self._censor_body]}

    @pytest.mark.record_ftp
    def test_before_record_response(self, vcr_config, request):
        """Test that before_record_response correctly censors the response body."""
        _ = vcr_config
        ftp = ftplib.FTP(FTP_HOST)
        ftp.login()
        ftp.cwd(FTP_DIR)
        bio = io.BytesIO()
        ftp.retrbinary(f"RETR {FTP_FILE}", bio.write)
        data = bio.getvalue()
        ftp.quit()

        record_mode = request.config.getoption("--record")
        if "ftp" not in (record_mode or []):  # Replay mode
            assert data == b"censored"

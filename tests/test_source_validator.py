import unittest
import asyncio
from services.source_validator import is_ip_allowed, validate_hostname, test_source_url


class TestSourceValidator(unittest.TestCase):
    def test_ip_filtering_private_and_loopback(self):
        self.assertFalse(is_ip_allowed("127.0.0.1")[0])
        self.assertFalse(is_ip_allowed("127.1.2.3")[0])
        self.assertFalse(is_ip_allowed("10.0.0.1")[0])
        self.assertFalse(is_ip_allowed("192.168.1.1")[0])
        self.assertFalse(is_ip_allowed("172.16.0.1")[0])
        self.assertFalse(is_ip_allowed("169.254.169.254")[0])
        self.assertFalse(is_ip_allowed("::1")[0])
        self.assertFalse(is_ip_allowed("fe80::1")[0])

    def test_ip_filtering_public(self):
        self.assertTrue(is_ip_allowed("8.8.8.8")[0])
        self.assertTrue(is_ip_allowed("1.1.1.1")[0])

    def test_hostname_blocking_local(self):
        self.assertFalse(validate_hostname("localhost")[0])
        self.assertFalse(validate_hostname("something.local")[0])
        self.assertFalse(validate_hostname("internal.lan")[0])

    def test_ssrf_url_blocking(self):
        async def run_checks():
            res1 = await test_source_url("http://127.0.0.1:8765/api/test")
            self.assertFalse(res1.success)
            self.assertTrue("SSRF" in (res1.error or "") or "차단" in (res1.error or ""))

            res2 = await test_source_url("http://169.254.169.254/latest/meta-data/")
            self.assertFalse(res2.success)

            res3 = await test_source_url("ftp://example.com/feed.xml")
            self.assertFalse(res3.success)
            self.assertIn("지원하지 않는 프로토콜", res3.error)

        asyncio.run(run_checks())


if __name__ == "__main__":
    unittest.main()

import sys
import urllib.request
import unittest
from bs4 import BeautifulSoup

sys.stdout.reconfigure(line_buffering=True, encoding='utf-8')
sys.stderr.reconfigure(line_buffering=True, encoding='utf-8')


class TestJobMasterParser(unittest.TestCase):
    def test_parse_jobmaster_structure(self):
        html_sample = """
        <div class="JobItem">
            <a class="CardHeader" href="/jobs/123">Python Developer</a>
            <div class="companyNameLink">Tech Company</div>
        </div>
        """
        soup = BeautifulSoup(html_sample, 'html.parser')
        job = soup.select_one('.JobItem')
        self.assertIsNotNone(job)
        title = job.select_one('.CardHeader')
        company = job.select_one('.companyNameLink')
        self.assertEqual(title.text.strip(), "Python Developer")
        self.assertEqual(company.text.strip(), "Tech Company")


if __name__ == "__main__":
    unittest.main()

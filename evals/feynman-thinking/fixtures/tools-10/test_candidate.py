import unittest
from candidate import total

class TotalTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(total([]), 0)
    def test_nonempty(self):
        self.assertEqual(total([3, 4]), 7)

if __name__ == '__main__':
    unittest.main()

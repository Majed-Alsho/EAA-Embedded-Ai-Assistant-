import unittest
def add(a, b):
    return a + b
class TestAddFunction(unittest.TestCase):
    def test_add(self):
        self.assertEqual(add(1, 1), 2)\nif __name__ == '__main__':
    unittest.main()
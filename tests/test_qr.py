import unittest

import qr


class QrCode(unittest.TestCase):
    def test_matrix_is_square_with_finder_patterns(self):
        grid = qr.matrix("http://192.168.1.5:8765/?t=abcdef")
        size = len(grid)
        self.assertGreaterEqual(size, 21)
        self.assertEqual((size - 17) % 4, 0, "QR sizes are 17 + 4 × version")
        self.assertTrue(all(len(row) == size for row in grid))
        for top, left in ((0, 0), (0, size - 7), (size - 7, 0)):  # the three corner squares
            self.assertTrue(all(grid[top][left + i] for i in range(7)))
            self.assertTrue(all(grid[top + 6][left + i] for i in range(7)))

    def test_image_size(self):
        picture = qr.image("hi", scale=8, border=4)
        self.assertEqual(picture.size[0], picture.size[1])

    def test_decodes(self):
        try:
            from pyzbar.pyzbar import decode
        except Exception:
            self.skipTest("pyzbar not installed")
        text = "http://192.168.1.5:8765/?t=Zono-test-123"
        self.assertEqual(decode(qr.image(text))[0].data.decode(), text)


if __name__ == "__main__":
    unittest.main()

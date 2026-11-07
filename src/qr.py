"""Small QR code generator (byte mode, error correction level M, versions 1-6). No dependencies."""

# raw codewords, number of error-correction blocks, error-correction codewords per block (level M)
_VERSIONS = {1: (26, 1, 10), 2: (44, 1, 16), 3: (70, 1, 26), 4: (100, 2, 18), 5: (134, 2, 24), 6: (172, 4, 16)}
_ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34]}
_REMAINDER = {1: 0, 2: 7, 3: 7, 4: 7, 5: 7, 6: 7}


def _mul(x, y):
    z = 0
    for i in range(7, -1, -1):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _divisor(degree):
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _mul(root, 0x02)
    return result


def _remainder(data, divisor):
    result = [0] * len(divisor)
    for byte in data:
        factor = byte ^ result.pop(0)
        result.append(0)
        for i, coefficient in enumerate(divisor):
            result[i] ^= _mul(coefficient, factor)
    return result


def _codewords(text):
    payload = text.encode("utf-8")
    for version in range(1, 7):
        raw, blocks, ec = _VERSIONS[version]
        capacity = raw - blocks * ec
        if 4 + 8 + len(payload) * 8 <= capacity * 8:
            break
    else:
        raise ValueError("Tekst is te lang voor deze QR-code.")
    bits = [0, 1, 0, 0] + [(len(payload) >> i) & 1 for i in range(7, -1, -1)]
    for byte in payload:
        bits += [(byte >> i) & 1 for i in range(7, -1, -1)]
    bits += [0] * min(4, capacity * 8 - len(bits))
    bits += [0] * (-len(bits) % 8)
    data = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = 0xEC
    while len(data) < capacity:
        data.append(pad)
        pad ^= 0xEC ^ 0x11
    short = raw // blocks
    long_blocks = raw % blocks
    divisor = _divisor(ec)
    chunks, position = [], 0
    for index in range(blocks):
        size = short - ec + (1 if index >= blocks - long_blocks else 0)
        chunk = data[position:position + size]
        position += size
        chunks.append((chunk, _remainder(chunk, divisor)))
    result = []
    for i in range(max(len(c) for c, _ in chunks)):
        result += [c[i] for c, _ in chunks if i < len(c)]
    for i in range(ec):
        result += [e[i] for _, e in chunks]
    return version, result


def _mask(mask, x, y):
    return (((x + y) % 2 == 0), (y % 2 == 0), (x % 3 == 0), ((x + y) % 3 == 0),
            ((x // 3 + y // 2) % 2 == 0), (x * y % 2 + x * y % 3 == 0),
            ((x * y % 2 + x * y % 3) % 2 == 0), (((x + y) % 2 + x * y % 3) % 2 == 0))[mask]


def matrix(text):
    """Return the QR code as a list of rows of booleans (True = dark), without quiet zone."""
    version, codewords = _codewords(text)
    size = 17 + 4 * version
    modules = [[False] * size for _ in range(size)]
    function = [[False] * size for _ in range(size)]

    def put(x, y, dark):
        modules[y][x] = dark
        function[y][x] = True

    for i in range(size):
        put(6, i, i % 2 == 0)
        put(i, 6, i % 2 == 0)
    for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                x, y = cx + dx, cy + dy
                if 0 <= x < size and 0 <= y < size:
                    distance = max(abs(dx), abs(dy))
                    put(x, y, distance not in (2, 4))
    positions = _ALIGN[version]
    for i, ax in enumerate(positions):
        for j, ay in enumerate(positions):
            if (i == 0 and j == 0) or (i == 0 and j == len(positions) - 1) or (i == len(positions) - 1 and j == 0):
                continue
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    put(ax + dx, ay + dy, max(abs(dx), abs(dy)) != 1)

    def format_bits(mask):
        data = (0 << 3) | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        return ((data << 10) | rem) ^ 0x5412

    def draw_format(mask):
        bits = format_bits(mask)
        bit = lambda i: (bits >> i) & 1 == 1
        for i in range(6):
            put(8, i, bit(i))
        put(8, 7, bit(6))
        put(8, 8, bit(7))
        put(7, 8, bit(8))
        for i in range(9, 15):
            put(14 - i, 8, bit(i))
        for i in range(8):
            put(size - 1 - i, 8, bit(i))
        for i in range(8, 15):
            put(8, size - 15 + i, bit(i))
        put(8, size - 8, True)

    draw_format(0)
    bits = []
    for byte in codewords:
        bits += [(byte >> i) & 1 for i in range(7, -1, -1)]
    bits += [0] * _REMAINDER[version]
    index = 0
    right = size - 1
    while right >= 1:
        if right == 6:
            right = 5
        for vertical in range(size):
            for j in range(2):
                x = right - j
                upward = ((right + 1) & 2) == 0
                y = size - 1 - vertical if upward else vertical
                if not function[y][x] and index < len(bits):
                    modules[y][x] = bits[index] == 1
                    index += 1
        right -= 2

    def apply(mask):
        for y in range(size):
            for x in range(size):
                if not function[y][x] and _mask(mask, x, y):
                    modules[y][x] = not modules[y][x]

    def penalty():
        score = 0
        for line in modules + [list(column) for column in zip(*modules)]:
            run, previous = 0, None
            for value in line:
                if value == previous:
                    run += 1
                    if run == 5:
                        score += 3
                    elif run > 5:
                        score += 1
                else:
                    run, previous = 1, value
        for y in range(size - 1):
            for x in range(size - 1):
                if modules[y][x] == modules[y][x + 1] == modules[y + 1][x] == modules[y + 1][x + 1]:
                    score += 3
        dark = sum(map(sum, modules))
        score += abs(dark * 20 - size * size * 10) // (size * size) * 10
        return score

    best, best_score = 0, None
    for mask in range(8):
        apply(mask)
        draw_format(mask)
        current = penalty()
        if best_score is None or current < best_score:
            best, best_score = mask, current
        apply(mask)
    apply(best)
    draw_format(best)
    return modules


def image(text, scale=8, border=4, dark=(11, 11, 15), light=(255, 255, 255)):
    from PIL import Image
    rows = matrix(text)
    size = len(rows)
    picture = Image.new("RGB", ((size + 2 * border) * scale,) * 2, light)
    pixels = picture.load()
    for y, row in enumerate(rows):
        for x, value in enumerate(row):
            if value:
                for dy in range(scale):
                    for dx in range(scale):
                        pixels[(x + border) * scale + dx, (y + border) * scale + dy] = dark
    return picture

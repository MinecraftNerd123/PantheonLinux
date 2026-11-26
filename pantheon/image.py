import base64
import struct
import zlib


class Frame:
    def __init__(self, width, height, data):
        if len(data) != width * height * 3:
            raise ValueError("Invalid image buffer.")
        self.width, self.height, self.data = width, height, bytes(data)

    def crop(self, x, y, width, height):
        if x == 0 and y == 0 and width == self.width and height == self.height:
            return self
        if x < 0 or y < 0 or width < 1 or height < 1 or x + width > self.width or y + height > self.height:
            raise ValueError("Crop region is outside the image.")
        stride, rows = self.width * 3, []
        for row in range(y, y + height):
            start = row * stride + x * 3
            rows.append(self.data[start:start + width * 3])
        return Frame(width, height, b"".join(rows))

    def pixel(self, x, y):
        i = (y * self.width + x) * 3
        return (self.data[i] << 16) | (self.data[i + 1] << 8) | self.data[i + 2]

    def png(self):
        stride = self.width * 3
        raw = b"".join(b"\x00" + self.data[r * stride:(r + 1) * stride] for r in range(self.height))

        def chunk(kind, body):
            return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

        header = struct.pack(">IIBBBBB", self.width, self.height, 8, 2, 0, 0, 0)
        return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")

    def data_url(self):
        return "data:image/png;base64," + base64.b64encode(self.png()).decode("ascii")


def parse_ppm(blob):
    if not blob.startswith(b"P6"):
        raise ValueError("Unexpected screenshot format.")
    fields, pos = [], 2
    while len(fields) < 3:
        while blob[pos:pos + 1].isspace():
            pos += 1
        if blob[pos:pos + 1] == b"#":
            while blob[pos:pos + 1] not in (b"\n", b""):
                pos += 1
            continue
        start = pos
        while not blob[pos:pos + 1].isspace():
            pos += 1
        fields.append(int(blob[start:pos]))
    pos += 1
    width, height, depth = fields
    if depth != 255:
        raise ValueError("Unsupported screenshot depth.")
    return Frame(width, height, blob[pos:pos + width * height * 3])


def load_file(path):
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
    pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
    if pixbuf.get_has_alpha():
        flat = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, pixbuf.get_width(), pixbuf.get_height())
        flat.fill(0x000000ff)
        pixbuf.composite(flat, 0, 0, pixbuf.get_width(), pixbuf.get_height(), 0, 0, 1, 1, GdkPixbuf.InterpType.NEAREST, 255)
        pixbuf = flat
    width, height, stride = pixbuf.get_width(), pixbuf.get_height(), pixbuf.get_rowstride()
    pixels = pixbuf.get_pixels()
    rows = [pixels[r * stride:r * stride + width * 3] for r in range(height)]
    return Frame(width, height, b"".join(rows))

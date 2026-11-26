#include <stdlib.h>
#include <string.h>

int pantheon_findtext(const unsigned char *rgb, int stride, int sw, int sh,
                      int threshold, const char *bits, int w, int h,
                      int err1, int err0, unsigned int *out, int max_out)
{
  int x, y, i, o, ok = 0, len1 = 0, len0 = 0, e1, e0, max, limit1, limit0;
  int r, rr, g, gg;
  unsigned char *ss;
  int *s1, *s0;
  unsigned int c;
  if (sw < 1 || sh < 1 || w < 1 || h < 1 || w > sw || h > sh)
    return 0;
  ss = (unsigned char *)malloc((size_t)sw * sh);
  s1 = (int *)malloc(sizeof(int) * (size_t)w * h);
  s0 = (int *)malloc(sizeof(int) * (size_t)w * h);
  if (!ss || !s1 || !s0) {
    free(ss); free(s1); free(s0);
    return -1;
  }
  for (y = 0, o = 0; y < h; y++)
    for (x = 0; x < w; x++, o++) {
      if (bits[o] == '1')
        s1[len1++] = y * sw + x;
      else
        s0[len0++] = y * sw + x;
    }
  c = ((unsigned int)threshold + 1) << 7;
  for (y = 0, i = 0; y < sh; y++) {
    const unsigned char *row = rgb + (size_t)y * stride;
    for (x = 0; x < sw; x++, i++) {
      const unsigned char *p = row + x * 3;
      int dark = (p[0] * 38 + p[1] * 75 + p[2] * 15) < (int)c;
      ss[i] = 4 | (dark << 1) | (!dark);
    }
  }
  limit1 = (int)(((long long)len1 * err1) >> 10);
  limit0 = (int)(((long long)len0 * err0) >> 10);
  if (limit1 >= len1) len1 = 0;
  if (limit0 >= len0) len0 = 0;
  max = len1 > len0 ? len1 : len0;
  for (y = 0; y <= sh - h; y++) {
    for (x = 0; x <= sw - w; x++) {
      o = y * sw + x;
      if (ss[o] < 4)
        continue;
      e1 = limit1;
      e0 = limit0;
      for (i = 0; i < max; i++) {
        if (i < len1 && (ss[o + s1[i]] & 2) == 0 && (--e1) < 0) goto NoMatch;
        if (i < len0 && (ss[o + s0[i]] & 1) == 0 && (--e0) < 0) goto NoMatch;
      }
      out[ok++] = ((unsigned int)y << 16) | (unsigned int)x;
      if (ok >= max_out)
        goto Done;
      r = y - h + 1; if (r < 0) r = 0;
      rr = y + h - 1; if (rr > sh - h) rr = sh - h;
      g = x - w + 1; if (g < 0) g = 0;
      gg = x + w - 1; if (gg > sw - w) gg = sw - w;
      {
        int a, b;
        for (a = r; a <= rr; a++)
          for (b = g; b <= gg; b++)
            ss[a * sw + b] &= 3;
      }
NoMatch:;
    }
  }
Done:
  free(ss); free(s1); free(s0);
  return ok;
}

int pantheon_dark_frame(const unsigned char *rgb, int width, int height)
{
  int x, y, corner = 8, inset;
  if (corner > width / 4) corner = width / 4;
  if (corner > height / 4) corner = height / 4;
  for (y = 0; y < height; y++) {
    const unsigned char *row = rgb + (size_t)y * width * 3;
    inset = (y < corner || y >= height - corner) ? corner : 0;
    for (x = inset; x < width - inset; x++)
      if (row[x * 3] | row[x * 3 + 1] | row[x * 3 + 2])
        return 0;
  }
  return 1;
}

#include "CZip.h"
#include <zlib.h>
uint32_t ts_crc(const uint8_t *data, size_t count) { return (uint32_t)crc32(0, data, (uInt)count); }
int ts_inflate(const uint8_t *src, size_t src_count, uint8_t *dst, size_t dst_count) {
    z_stream stream = {0};
    stream.next_in = (Bytef *)src; stream.avail_in = (uInt)src_count;
    stream.next_out = dst; stream.avail_out = (uInt)dst_count;
    if (inflateInit2(&stream, -MAX_WBITS) != Z_OK) return 0;
    int result = inflate(&stream, Z_FINISH);
    int valid = result == Z_STREAM_END && stream.total_out == dst_count && stream.total_in == src_count;
    inflateEnd(&stream);
    return valid;
}

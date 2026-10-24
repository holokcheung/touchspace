#include <stdint.h>
#include <stddef.h>
uint32_t ts_crc(const uint8_t *data, size_t count);
int ts_inflate(const uint8_t *src, size_t src_count, uint8_t *dst, size_t dst_count);

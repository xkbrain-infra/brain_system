#ifndef BASE64_H
#define BASE64_H

#include <stdlib.h>

// Simple base64 encoding
char *base64_encode(const unsigned char *input, size_t length);

// Simple base64 decoding
unsigned char *base64_decode(const char *input, size_t *output_length);

// Free buffer from base64_decode
void base64_free(unsigned char *buf);

#endif

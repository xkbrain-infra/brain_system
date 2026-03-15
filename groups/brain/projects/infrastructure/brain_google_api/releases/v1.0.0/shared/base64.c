#include "base64.h"
#include <stdlib.h>
#include <string.h>

static const char base64_chars[] =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

char *base64_encode(const unsigned char *input, size_t length) {
    size_t output_length = ((length + 2) / 3) * 4 + 1;
    char *output = malloc(output_length);
    if (!output) return NULL;

    size_t i = 0;
    size_t j = 0;

    while (i < length) {
        unsigned char octet_a = i < length ? input[i++] : 0;
        unsigned char octet_b = i < length ? input[i++] : 0;
        unsigned char octet_c = i < length ? input[i++] : 0;

        unsigned int triple = (octet_a << 16) + (octet_b << 8) + octet_c;

        output[j++] = base64_chars[(triple >> 18) & 0x3F];
        output[j++] = base64_chars[(triple >> 12) & 0x3F];
        output[j++] = base64_chars[(triple >> 6) & 0x3F];
        output[j++] = base64_chars[triple & 0x3F];
    }

    size_t padding = (length % 3);
    if (padding > 0) {
        for (size_t p = 0; p < 3 - padding; p++) {
            output[j - 1 - p] = '=';
        }
    }

    output[j] = '\0';
    return output;
}

static int base64_decode_char(char c) {
    if (c >= 'A' && c <= 'Z') return c - 'A';
    if (c >= 'a' && c <= 'z') return c - 'a' + 26;
    if (c >= '0' && c <= '9') return c - '0' + 52;
    if (c == '+') return 62;
    if (c == '/') return 63;
    return -1;
}

unsigned char *base64_decode(const char *input, size_t *output_length) {
    size_t input_len = strlen(input);
    if (input_len % 4 != 0) return NULL;

    size_t padding = 0;
    if (input_len > 0 && input[input_len - 1] == '=') padding++;
    if (input_len > 1 && input[input_len - 2] == '=') padding++;

    // Calculate output length: each 4 chars -> 3 bytes, minus padding
    size_t output_len = (input_len / 4) * 3;
    if (padding == 2) output_len -= 2;
    else if (padding == 1) output_len -= 1;

    unsigned char *output = malloc(output_len);
    if (!output) return NULL;

    size_t i = 0;
    size_t j = 0;

    while (i < input_len) {
        int val[4];
        val[0] = base64_decode_char(input[i++]);
        val[1] = base64_decode_char(input[i++]);
        val[2] = (input[i] != '=') ? base64_decode_char(input[i++]) : (i++, 0);
        val[3] = (input[i] != '=') ? base64_decode_char(input[i++]) : (i++, 0);

        unsigned int triple = (val[0] << 18) + (val[1] << 12) + (val[2] << 6) + val[3];

        // Output 3 bytes, but respect padding
        if (j < output_len) output[j++] = (triple >> 16) & 0xFF;
        if (j < output_len) output[j++] = (triple >> 8) & 0xFF;
        if (j < output_len) output[j++] = triple & 0xFF;
    }

    *output_length = output_len;
    return output;
}

void base64_free(unsigned char *buf) {
    free(buf);
}

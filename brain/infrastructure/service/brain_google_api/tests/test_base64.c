/**
 * Simple base64 test
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "base64.h"

void print_hex(const char *label, const unsigned char *data, size_t len) {
    printf("%s: ", label);
    for (size_t i = 0; i < len; i++) {
        printf("%02x ", data[i]);
    }
    printf("\n");
}

int main(void) {
    // Test 1: Simple string
    const char *test1 = "Hello";
    char *enc1 = base64_encode((const unsigned char *)test1, strlen(test1));
    printf("Test1: '%s' -> '%s'\n", test1, enc1);

    size_t dec_len1 = 0;
    unsigned char *dec1 = base64_decode(enc1, &dec_len1);
    print_hex("dec1 hex", dec1, dec_len1);
    printf("Test1: '%s' -> len=%zu, match=%d\n", dec1, dec_len1,
           strlen(test1) == dec_len1 && memcmp(test1, dec1, dec_len1) == 0);

    // Test 2: Binary data
    unsigned char bin[] = {0x00, 0x01, 0x02, 0xFF};
    char *enc2 = base64_encode(bin, sizeof(bin));
    printf("Test2: bin -> '%s'\n", enc2);

    size_t dec_len2 = 0;
    unsigned char *dec2 = base64_decode(enc2, &dec_len2);
    print_hex("dec2 hex", dec2, dec_len2);
    printf("Test2: match=%d\n", dec_len2 == sizeof(bin) && memcmp(bin, dec2, sizeof(bin)) == 0);

    free(enc1);
    free(dec1);
    free(enc2);
    free(dec2);

    // Test 3: "A" -> "QQ=="
    const char *test3 = "A";
    char *enc3 = base64_encode((const unsigned char *)test3, 1);
    printf("Test3: 'A' -> '%s'\n", enc3);

    size_t dec_len3 = 0;
    unsigned char *dec3 = base64_decode(enc3, &dec_len3);
    print_hex("dec3 hex", dec3, dec_len3);
    printf("Test3: match=%d\n", dec_len3 == 1 && memcmp(test3, dec3, 1) == 0);
    free(enc3);
    free(dec3);

    return 0;
}

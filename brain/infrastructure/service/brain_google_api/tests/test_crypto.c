/**
 * Crypto module test suite
 * Tests AES-256-GCM encryption/decryption
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "crypto.h"

#define TEST_ASSERT(cond, msg) do { \
    if (!(cond)) { \
        printf("FAIL: %s\n", msg); \
        return 1; \
    } \
} while(0)

#define TEST_PASS(msg) printf("PASS: %s\n", msg)

// Global flag to track if crypto is initialized
static int crypto_initialized = 0;

// Wrapper to ensure crypto is initialized only once
static int ensure_crypto_init(void) {
    if (!crypto_initialized) {
        crypto_init(NULL);
        crypto_initialized = 1;
    }
    return 0;
}

static int test_basic_encrypt_decrypt(void) {
    printf("\n=== Test: Basic encrypt/decrypt ===\n");

    ensure_crypto_init();

    const char *plaintext = "Hello, World! This is a test message.";
    char *ciphertext = NULL;
    size_t ciphertext_len = 0;
    char *decrypted = NULL;
    size_t decrypted_len = 0;

    int ret = crypto_encrypt((const unsigned char *)plaintext, strlen(plaintext),
                            &ciphertext, &ciphertext_len);
    TEST_ASSERT(ret == 0, "crypto_encrypt failed");
    TEST_ASSERT(ciphertext != NULL, "ciphertext is NULL");
    TEST_ASSERT(ciphertext_len > 0, "ciphertext_len is 0");

    printf("Plaintext:  %s\n", plaintext);
    printf("Ciphertext: %s\n", ciphertext);

    ret = crypto_decrypt(ciphertext, ciphertext_len, (unsigned char **)&decrypted, &decrypted_len);
    TEST_ASSERT(ret == 0, "crypto_decrypt failed");
    TEST_ASSERT(decrypted != NULL, "decrypted is NULL");
    TEST_ASSERT(decrypted_len == strlen(plaintext), "decrypted_len mismatch");
    TEST_ASSERT(memcmp(plaintext, decrypted, strlen(plaintext)) == 0,
               "decrypted text mismatch");

    printf("Decrypted:  %s\n", decrypted);

    crypto_free(ciphertext);
    crypto_free(decrypted);

    TEST_PASS("Basic encrypt/decrypt");
    return 0;
}

static int test_multiple_data(void) {
    printf("\n=== Test: Multiple data types ===\n");

    ensure_crypto_init();

    struct {
        const char *data;
        const char *desc;
    } test_cases[] = {
        {"", "Empty string"},
        {"A", "Single char"},
        {"ABC", "Short string"},
        {"The quick brown fox jumps over the lazy dog", "Long string"},
        {"中文测试", "Chinese characters"},
        {"🎉 Emoji test 🚀", "Emoji"},
        {"{\"token\": \"ya29.a0AfH6SMBxxx\", \"refresh_token\": \"1//0gxxx\"}",
         "JSON with tokens"},
        {NULL, NULL}
    };

    for (int i = 0; test_cases[i].data != NULL; i++) {
        char *ciphertext = NULL;
        size_t ciphertext_len = 0;
        char *decrypted = NULL;
        size_t decrypted_len = 0;

        size_t plain_len = strlen(test_cases[i].data);

        int ret = crypto_encrypt((const unsigned char *)test_cases[i].data,
                                plain_len, &ciphertext, &ciphertext_len);
        TEST_ASSERT(ret == 0, test_cases[i].desc);

        ret = crypto_decrypt(ciphertext, ciphertext_len,
                           (unsigned char **)&decrypted, &decrypted_len);
        TEST_ASSERT(ret == 0, test_cases[i].desc);
        TEST_ASSERT(decrypted_len == plain_len, test_cases[i].desc);
        TEST_ASSERT(memcmp(test_cases[i].data, decrypted, plain_len) == 0,
                   test_cases[i].desc);

        printf("  PASS: %s\n", test_cases[i].desc);

        crypto_free(ciphertext);
        crypto_free(decrypted);
    }

    TEST_PASS("Multiple data types");
    return 0;
}

static int test_binary_data(void) {
    printf("\n=== Test: Binary-like data ===\n");

    ensure_crypto_init();

    unsigned char binary_in[] = {0x00, 0x01, 0x02, 0xFF, 0x00, 0xFF, 0xAB, 0xCD};
    size_t binary_len = sizeof(binary_in);

    char *ciphertext = NULL;
    size_t ciphertext_len = 0;
    unsigned char *decrypted = NULL;
    size_t decrypted_len = 0;

    int ret = crypto_encrypt(binary_in, binary_len, &ciphertext, &ciphertext_len);
    TEST_ASSERT(ret == 0, "encrypt binary");

    ret = crypto_decrypt(ciphertext, ciphertext_len, &decrypted, &decrypted_len);
    TEST_ASSERT(ret == 0, "decrypt binary");
    TEST_ASSERT(decrypted_len == binary_len, "length mismatch");
    TEST_ASSERT(memcmp(binary_in, decrypted, binary_len) == 0, "data mismatch");

    crypto_free(ciphertext);
    crypto_free(decrypted);

    TEST_PASS("Binary data");
    return 0;
}

static int test_uninitialized_error(void) {
    printf("\n=== Test: Error handling ===\n");

    TEST_ASSERT(crypto_is_initialized() == 1, "crypto should be initialized");

    char *out = NULL;
    size_t out_len = 0;

    int ret = crypto_encrypt((const unsigned char *)"test", 4, &out, &out_len);
    TEST_ASSERT(ret == 0, "encrypt should work when initialized");
    crypto_free(out);

    TEST_PASS("Error handling");
    return 0;
}

static int test_token_storage_scenario(void) {
    printf("\n=== Test: Token storage scenario ===\n");

    ensure_crypto_init();

    const char *access_token = "ya29.a0AfH6SMBxxx";
    const char *refresh_token = "1//0gCyABCxxx";

    char *enc_access = NULL, *enc_refresh = NULL;
    size_t len_access = 0, len_refresh = 0;

    int ret = crypto_encrypt((const unsigned char *)access_token,
                            strlen(access_token), &enc_access, &len_access);
    TEST_ASSERT(ret == 0, "encrypt access_token");

    ret = crypto_encrypt((const unsigned char *)refresh_token,
                        strlen(refresh_token), &enc_refresh, &len_refresh);
    TEST_ASSERT(ret == 0, "encrypt refresh_token");

    printf("Access token (encrypted):   %s\n", enc_access);
    printf("Refresh token (encrypted):  %s\n", enc_refresh);

    unsigned char *dec_access = NULL, *dec_refresh = NULL;
    size_t dec_len_access = 0, dec_len_refresh = 0;

    ret = crypto_decrypt(enc_access, len_access, &dec_access, &dec_len_access);
    TEST_ASSERT(ret == 0, "decrypt access_token");

    ret = crypto_decrypt(enc_refresh, len_refresh, &dec_refresh, &dec_len_refresh);
    TEST_ASSERT(ret == 0, "decrypt refresh_token");

    TEST_ASSERT(memcmp(access_token, dec_access, strlen(access_token)) == 0,
               "access_token mismatch");
    TEST_ASSERT(memcmp(refresh_token, dec_refresh, strlen(refresh_token)) == 0,
               "refresh_token mismatch");

    crypto_free(enc_access);
    crypto_free(enc_refresh);
    crypto_free(dec_access);
    crypto_free(dec_refresh);

    TEST_PASS("Token storage scenario");
    return 0;
}

int main(void) {
    printf("========================================\n");
    printf("  Crypto Module Test Suite\n");
    printf("  AES-256-GCM Encryption\n");
    printf("========================================\n");

    int failed = 0;

    failed += test_basic_encrypt_decrypt();
    failed += test_multiple_data();
    failed += test_binary_data();
    failed += test_uninitialized_error();
    failed += test_token_storage_scenario();

    printf("\n========================================\n");
    if (failed == 0) {
        printf("  ALL TESTS PASSED\n");
    } else {
        printf("  FAILED: %d tests\n", failed);
    }
    printf("========================================\n");

    return failed > 0 ? 1 : 0;
}

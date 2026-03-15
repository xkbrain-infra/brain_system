#include "crypto.h"
#include "base64.h"
#include "logger.h"
#include <openssl/evp.h>
#include <openssl/rand.h>
#include <openssl/err.h>
#include <stdlib.h>
#include <string.h>

#define AES_KEY_LEN 32      // 256 bits
#define IV_LEN 12           // 96 bits for GCM
#define AUTH_TAG_LEN 16     // 128 bits
#define SALT_LEN 16

static unsigned char key[AES_KEY_LEN];
static int initialized = 0;

static void print_openssl_error(const char *msg) {
    unsigned long err = ERR_get_error();
    char err_buf[256];
    ERR_error_string_n(err, err_buf, sizeof(err_buf));
    log_error("%s: %s", msg, err_buf);
}

int crypto_init(const char *key_path) {
    const char *env_key = getenv("BRAIN_GOOGLE_API_KEY");

    if (env_key && strlen(env_key) >= AES_KEY_LEN * 2) {
        // Hex string key
        for (int i = 0; i < AES_KEY_LEN; i++) {
            char byte_str[3] = {env_key[i*2], env_key[i*2+1], 0};
            key[i] = (unsigned char)strtol(byte_str, NULL, 16);
        }
        initialized = 1;
        log_info("Crypto initialized from environment (hex key)");
        return 0;
    }

    if (env_key && strlen(env_key) >= AES_KEY_LEN) {
        // Raw key
        memcpy(key, env_key, AES_KEY_LEN);
        initialized = 1;
        log_info("Crypto initialized from environment (raw key)");
        return 0;
    }

    if (key_path) {
        FILE *f = fopen(key_path, "rb");
        if (f) {
            size_t read = fread(key, 1, AES_KEY_LEN, f);
            fclose(f);
            if (read == AES_KEY_LEN) {
                initialized = 1;
                log_info("Crypto initialized from key file");
                return 0;
            }
        }
    }

    // Generate random key if no key provided
    RAND_bytes(key, AES_KEY_LEN);
    initialized = 1;
    log_warn("No encryption key provided, generated random key (will not persist!)");
    return 0;
}

int crypto_encrypt(const unsigned char *plaintext, size_t plaintext_len,
                   char **out_ciphertext, size_t *out_len) {
    if (!initialized) {
        log_error("Crypto not initialized");
        return -1;
    }

    unsigned char iv[IV_LEN];
    RAND_bytes(iv, IV_LEN);

    EVP_CIPHER_CTX *ctx = EVP_CIPHER_CTX_new();
    if (!ctx) {
        log_error("Failed to create cipher context");
        return -1;
    }

    unsigned char ciphertext[plaintext_len];
    unsigned char auth_tag[AUTH_TAG_LEN];
    int len = 0, ciphertext_len = 0;

    if (EVP_EncryptInit_ex(ctx, EVP_aes_256_gcm(), NULL, NULL, NULL) != 1) {
        print_openssl_error("EVP_EncryptInit_ex failed");
        EVP_CIPHER_CTX_free(ctx);
        return -1;
    }

    if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_IVLEN, IV_LEN, NULL) != 1) {
        print_openssl_error("EVP_CTRL_GCM_SET_IVLEN failed");
        EVP_CIPHER_CTX_free(ctx);
        return -1;
    }

    if (EVP_EncryptInit_ex(ctx, NULL, NULL, key, iv) != 1) {
        print_openssl_error("Encrypt init with iv failed");
        EVP_CIPHER_CTX_free(ctx);
        return -1;
    }

    if (EVP_EncryptUpdate(ctx, ciphertext, &len, plaintext, plaintext_len) != 1) {
        print_openssl_error("EVP_EncryptUpdate failed");
        EVP_CIPHER_CTX_free(ctx);
        return -1;
    }
    ciphertext_len = len;

    if (EVP_EncryptFinal_ex(ctx, ciphertext + len, &len) != 1) {
        print_openssl_error("EVP_EncryptFinal failed");
        EVP_CIPHER_CTX_free(ctx);
        return -1;
    }
    ciphertext_len += len;

    if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_GET_TAG, AUTH_TAG_LEN, auth_tag) != 1) {
        print_openssl_error("EVP_CTRL_GCM_GET_TAG failed");
        EVP_CIPHER_CTX_free(ctx);
        return -1;
    }

    EVP_CIPHER_CTX_free(ctx);

    // Format: iv (12) + auth_tag (16) + ciphertext
    unsigned char combined[IV_LEN + AUTH_TAG_LEN + ciphertext_len];
    memcpy(combined, iv, IV_LEN);
    memcpy(combined + IV_LEN, auth_tag, AUTH_TAG_LEN);
    memcpy(combined + IV_LEN + AUTH_TAG_LEN, ciphertext, ciphertext_len);

    // Base64 encode
    *out_ciphertext = base64_encode(combined, IV_LEN + AUTH_TAG_LEN + ciphertext_len);
    *out_len = strlen(*out_ciphertext);

    return 0;
}

int crypto_decrypt(const char *ciphertext_b64, size_t ciphertext_b64_len,
                   unsigned char **out_plaintext, size_t *out_len) {
    (void)ciphertext_b64_len; // base64_decode calculates length internally
    if (!initialized) {
        log_error("Crypto not initialized");
        return -1;
    }

    // Base64 decode
    size_t combined_len = 0;
    unsigned char *combined = base64_decode(ciphertext_b64, &combined_len);
    if (!combined || combined_len < IV_LEN + AUTH_TAG_LEN) {
        log_error("Base64 decode failed or data too short");
        free(combined);
        return -1;
    }

    unsigned char iv[IV_LEN];
    unsigned char auth_tag[AUTH_TAG_LEN];
    unsigned char *ciphertext = combined + IV_LEN + AUTH_TAG_LEN;
    size_t ciphertext_len = combined_len - IV_LEN - AUTH_TAG_LEN;

    memcpy(iv, combined, IV_LEN);
    memcpy(auth_tag, combined + IV_LEN, AUTH_TAG_LEN);

    EVP_CIPHER_CTX *ctx = EVP_CIPHER_CTX_new();
    if (!ctx) {
        log_error("Failed to create cipher context");
        free(combined);
        return -1;
    }

    if (EVP_DecryptInit_ex(ctx, EVP_aes_256_gcm(), NULL, NULL, NULL) != 1) {
        print_openssl_error("EVP_DecryptInit_ex failed");
        EVP_CIPHER_CTX_free(ctx);
        free(combined);
        return -1;
    }

    if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_IVLEN, IV_LEN, NULL) != 1) {
        print_openssl_error("EVP_CTRL_GCM_SET_IVLEN failed");
        EVP_CIPHER_CTX_free(ctx);
        free(combined);
        return -1;
    }

    if (EVP_DecryptInit_ex(ctx, NULL, NULL, key, iv) != 1) {
        print_openssl_error("Decrypt init failed");
        EVP_CIPHER_CTX_free(ctx);
        free(combined);
        return -1;
    }

    unsigned char *plaintext = malloc(ciphertext_len + 1);
    int len = 0, plaintext_len = 0;

    if (EVP_DecryptUpdate(ctx, plaintext, &len, ciphertext, ciphertext_len) != 1) {
        print_openssl_error("EVP_DecryptUpdate failed");
        EVP_CIPHER_CTX_free(ctx);
        free(plaintext);
        free(combined);
        return -1;
    }
    plaintext_len = len;

    if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_TAG, AUTH_TAG_LEN, auth_tag) != 1) {
        print_openssl_error("EVP_CTRL_GCM_SET_TAG failed");
        EVP_CIPHER_CTX_free(ctx);
        free(plaintext);
        free(combined);
        return -1;
    }

    int ret = EVP_DecryptFinal_ex(ctx, plaintext + len, &len);
    EVP_CIPHER_CTX_free(ctx);
    free(combined);

    if (ret != 1) {
        log_error("Authentication tag verification failed");
        free(plaintext);
        return -1;
    }

    plaintext_len += len;
    plaintext[plaintext_len] = '\0';

    *out_plaintext = plaintext;
    *out_len = plaintext_len;

    return 0;
}

void crypto_free(void *ptr) {
    if (ptr) {
        memset(ptr, 0, strlen(ptr));
        free(ptr);
    }
}

int crypto_is_initialized(void) {
    return initialized;
}

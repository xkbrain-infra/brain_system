#ifndef CRYPTO_H
#define CRYPTO_H

#include <stddef.h>

/**
 * Crypto module for brain-google-api
 * Provides AES-256-GCM encryption for sensitive data (tokens, credentials)
 */

// Initialize crypto with key from environment or file
int crypto_init(const char *key_path);

// Encrypt data (AES-256-GCM)
// Output: base64(ciphertext + iv + auth_tag)
int crypto_encrypt(const unsigned char *plaintext, size_t plaintext_len,
                   char **out_ciphertext, size_t *out_len);

// Decrypt data
int crypto_decrypt(const char *ciphertext, size_t ciphertext_len,
                   unsigned char **out_plaintext, size_t *out_len);

// Free allocated memory
void crypto_free(void *ptr);

// Get crypto status
int crypto_is_initialized(void);

#endif // CRYPTO_H

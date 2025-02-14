/**
 * @file
 * @ingroup crypto
 *
 * @brief  SHA256 hashing implementation using CryptoCell.
 *
 * @author Alexandre Abadie <alexandre.abadie@inria.fr>
 *
 * @copyright Inria, 2023
 */

#include <stdint.h>

#include <nrf.h>
#include "sha256.h"
#include "soft_sha256.h"

static SHA256_CTX _hash_context;

void sha256_init(void) {
    soft_sha256_init(&_hash_context);
}

void sha256_update(const uint8_t *data, size_t len) {
    soft_sha256_update(&_hash_context, (uint8_t *)data, len);
}

void sha256_finalize(uint8_t *digest) {
    soft_sha256_final(&_hash_context, (BYTE *)digest);
}

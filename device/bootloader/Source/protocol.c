/**
 * @file
 * @ingroup drv_protocol
 *
 * @brief  nRF52833-specific definition of the "protocol" driver module.
 *
 * @author Alexandre Abadie <alexandre.abadie@inria.fr>
 *
 * @copyright Inria, 2022
 */

#include <stdint.h>
#include <string.h>
#include "device.h"
#include "protocol.h"

size_t protocol_header_to_buffer(uint8_t *buffer, uint64_t dst) {
    uint64_t src = db_device_id();

    protocol_header_t header = {
        .version     = FIRMWARE_VERSION,
        .packet_type = PACKET_DATA,
        .dst         = dst,
        .src         = src,
    };

    memcpy(buffer, &header, sizeof(protocol_header_t));
    return sizeof(protocol_header_t);
}

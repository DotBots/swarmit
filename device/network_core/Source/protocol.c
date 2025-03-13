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

//=========================== public ===========================================

static size_t _protocol_header_to_buffer(uint8_t *buffer, uint64_t dst, packet_type_t packet_type) {
    uint64_t src = db_device_id();

    protocol_header_t header = {
        .version     = FIRMWARE_VERSION,
        .packet_type = packet_type,
        .dst         = dst,
        .src         = src,
    };
    memcpy(buffer, &header, sizeof(protocol_header_t));
    return sizeof(protocol_header_t);
}

size_t protocol_header_to_buffer(uint8_t *buffer, uint64_t dst) {
    return _protocol_header_to_buffer(buffer, dst, PACKET_DATA);
}

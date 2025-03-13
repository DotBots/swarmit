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

size_t db_protocol_advertizement_to_buffer(uint8_t *buffer, application_type_t application) {
    size_t pos = 0;
    buffer[pos++] = PROTOCOL_ADVERTISEMENT;
    buffer[pos++] = application;
    return pos;
}

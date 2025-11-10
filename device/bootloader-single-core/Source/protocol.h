#ifndef __PROTOCOL_H
#define __PROTOCOL_H

/**
 * @defgroup    drv_protocol    DotBot protocol implementation
 * @ingroup     drv
 * @brief       Definitions and implementations of the DotBot protocol
 *
 * @{
 * @file
 * @author Alexandre Abadie <alexandre.abadie@inria.fr>
 * @copyright Inria, 2022
 * @}
 */

#include <stdlib.h>
#include <stdint.h>

//=========================== defines ==========================================

#define FIRMWARE_VERSION  (1)                   ///< Version of the firmware
#define SWARM_ID          (0x0000)              ///< Default swarm ID
#define BROADCAST_ADDRESS 0xffffffffffffffffUL  ///< Broadcast address
#define GATEWAY_ADDRESS   0x0000000000000000UL  ///< Gateway address

#define SWRMT_PREAMBLE_LENGTH       (8U)
#define SWRMT_OTA_CHUNK_SIZE        (128U)

typedef struct __attribute__((packed)) {
    uint32_t image_size;                        ///< User image size in bytes
    uint32_t chunk_count;
} swrmt_ota_start_pkt_t;

typedef struct __attribute__((packed)) {
    uint32_t index;                             ///< Index of the chunk
    uint8_t  chunk_size;                        ///< Size of the chunk
    uint8_t  sha[8];
    uint8_t  chunk[SWRMT_OTA_CHUNK_SIZE];       ///< Bytes array of the firmware chunk
} swrmt_ota_chunk_pkt_t;

typedef enum {
    SWRMT_APPLICATION_READY = 0,
    SWRMT_APPLICATION_RUNNING,
    SWRMT_APPLICATION_STOPPING,
    SWRMT_APPLICATION_RESETTING,
    SWRMT_APPLICATION_PROGRAMMING,
} swrmt_application_status_t;

typedef enum {
    SWRMT_MSG_STATUS = 0x80,
    SWRMT_MSG_START = 0x81,
    SWRMT_MSG_STOP = 0x82,
    SWRMT_MSG_RESET = 0x83,
    SWRMT_MSG_OTA_START = 0x84,
    SWRMT_MSG_OTA_CHUNK = 0x85,
    SWRMT_MSG_OTA_START_ACK = 0x86,
    SWRMT_MSG_OTA_CHUNK_ACK = 0x87,
    SWRMT_MSG_GPIO_EVENT = 0x88,
    SWRMT_MSG_LOG_EVENT = 0x89,
} swrmt_message_type_t;

/// Application type
typedef enum {
    DotBot        = 0,  ///< DotBot application
    SailBot       = 1,  ///< SailBot application
    FreeBot       = 2,  ///< FreeBot application
    XGO           = 3,  ///< XGO application
    LH2_mini_mote = 4,  ///< LH2 mini mote application
} application_type_t;

typedef enum {
    SWRMT_DEVICE_TYPE_UNKNOWN = 0,
    SWRMT_DEVICE_TYPE_DOTBOTV3 = 1,
    SWRMT_DEVICE_TYPE_DOTBOTV2 = 2,
    SWRMT_DEVICE_TYPE_NRF5340DK = 3,
    SWRMT_DEVICE_TYPE_NRF52840DK = 4,
} swrmt_device_type_t;

typedef struct __attribute__((packed)) {
    swrmt_message_type_t    type;
    uint8_t                 data[255];
} swrmt_request_t;

#endif

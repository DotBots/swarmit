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
    uint32_t index;                             ///< Index of the chunk
    uint8_t  chunk_size;                        ///< Size of the chunk
    uint8_t  chunk[SWRMT_OTA_CHUNK_SIZE];       ///< Bytes array of the firmware chunk
} swrmt_ota_chunk_pkt_t;

typedef enum {
    SWRMT_APPLICATION_READY = 0,
    SWRMT_APPLICATION_RUNNING,
    SWRMT_APPLICATION_STOPPING,
    SWRMT_APPLICATION_RESETTING,
} swrmt_application_status_t;

typedef enum {
    SWRMT_REQUEST_STATUS = 0x80,
    SWRMT_REQUEST_START = 0x81,
    SWRMT_REQUEST_STOP = 0x82,
    SWRMT_REQUEST_RESET = 0x83,
    SWRMT_REQUEST_OTA_START = 0x84,
    SWRMT_REQUEST_OTA_CHUNK = 0x85,
} swrmt_request_type_t;

typedef enum {
    SWRMT_NOTIFICATION_STATUS = 0x90,
    SWRMT_NOTIFICATION_STARTED = 0x91,
    SWRMT_NOTIFICATION_STOPPED = 0x92,
    SWRMT_NOTIFICATION_OTA_START_ACK = 0x93,
    SWRMT_NOTIFICATION_OTA_CHUNK_ACK = 0x94,
    SWRMT_NOTIFICATION_GPIO_EVENT = 0x95,
    SWRMT_NOTIFICATION_LOG_EVENT = 0x96,
} swrmt_notification_type_t;

/// Application type
typedef enum {
    DotBot        = 0,  ///< DotBot application
    SailBot       = 1,  ///< SailBot application
    FreeBot       = 2,  ///< FreeBot application
    XGO           = 3,  ///< XGO application
    LH2_mini_mote = 4,  ///< LH2 mini mote application
} application_type_t;

/// Protocol packet type
typedef enum {
    PACKET_BEACON = 1,
    PACKET_JOIN_REQUEST = 2,
    PACKET_JOIN_RESPONSE = 4,
    PACKET_KEEPALIVE = 8,
    PACKET_DATA = 16,
} packet_type_t;

/// DotBot protocol data type (just the LH related ones)
typedef enum {
    PROTOCOL_LH2_RAW_DATA       = 2,   ///< Lighthouse 2 raw data
    PROTOCOL_LH2_LOCATION       = 3,   ///< Lighthouse processed locations
    PROTOCOL_ADVERTISEMENT      = 4,   ///< DotBot advertisements
    PROTOCOL_DOTBOT_DATA        = 6,   ///< DotBot specific data (for now location and direction)
    PROTOCOL_LH2_PROCESSED_DATA = 12,  ///< Lighthouse 2 data processed at the DotBot
} protocol_data_type_t;

/// DotBot protocol header
typedef struct __attribute__((packed)) {
    uint8_t       version;      ///< Version of the firmware
    packet_type_t packet_type;  ///< Type of packet
    uint64_t      dst;          ///< Destination address of this packet
    uint64_t      src;          ///< Source address of this packet
} protocol_header_t;

///< DotBot protocol TDMA table update [all units are in microseconds]
typedef struct __attribute__((packed)) {
    uint32_t frame_period;       ///< duration of a full TDMA frame
    uint32_t rx_start;           ///< start to listen for packets
    uint16_t rx_duration;        ///< duration of the RX period
    uint32_t tx_start;           ///< start of slot for transmission
    uint16_t tx_duration;        ///< duration of the TX period
    uint32_t next_period_start;  ///< time until the start of the next TDMA frame
} protocol_tdma_table_t;

///< DotBot protocol sync messages marks the start of a TDMA frame [all units are in microseconds]
typedef struct __attribute__((packed)) {
    uint32_t frame_period;  ///< duration of a full TDMA frame
} protocol_sync_frame_t;

/// DotBot protocol LH2 computed location
typedef struct __attribute__((packed)) {
    uint32_t x;  ///< X coordinate, multiplied by 1e6
    uint32_t y;  ///< Y coordinate, multiplied by 1e6
} protocol_lh2_location_t;

/**
 * @brief   Write an application advertizement packet in a buffer
 *
 * @param[out]  buffer      Bytes array to write to
 * @param[in]   application Type of application advertized
 *
 * @return                  Number of bytes written in the buffer
 */
size_t db_protocol_advertizement_to_buffer(uint8_t *buffer, application_type_t application);

#endif

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

#define FIRMWARE_VERSION  (9)                   ///< Version of the firmware
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
    SWRMT_EXPERIMENT_READY,
    SWRMT_EXPERIMENT_RUNNING,
} swrmt_experiment_status_t;

typedef enum {
    SWRMT_REQUEST_STATUS = 0x80,
    SWRMT_REQUEST_START = 0x81,
    SWRMT_REQUEST_STOP = 0x82,
    SWRMT_REQUEST_OTA_START = 0x83,
    SWRMT_REQUEST_OTA_CHUNK = 0x84,
} swrmt_request_type_t;

typedef enum {
    SWRMT_NOTIFICATION_STATUS = 0x85,
    SWRMT_NOTIFICATION_OTA_START_ACK = 0x86,
    SWRMT_NOTIFICATION_OTA_CHUNK_ACK = 0x87,
    SWRMT_NOTIFICATION_GPIO_EVENT = 0x88,
    SWRMT_NOTIFICATION_LOG_EVENT = 0x89,
} swrmt_notification_type_t;

/// Protocol packet type
typedef enum {
    PACKET_BEACON            = 1,  ///< Beacon packet
    PACKET_JOIN_REQUEST      = 2,  ///< Join request packet
    PACKET_JOIN_RESPONSE     = 3,  ///< Join response packet
    PACKET_LEAVE             = 4,  ///< Leave packet
    PACKET_DATA              = 5,  ///< Data packet
} packet_type_t;

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

/**
 * @brief   Write the protocol header in a buffer
 *
 * @param[out]  buffer      Bytes array to write to
 * @param[in]   dst         Destination address written in the header
 *
 * @return                  Number of bytes written in the buffer
 */
size_t protocol_header_to_buffer(uint8_t *buffer, uint64_t dst);

#endif

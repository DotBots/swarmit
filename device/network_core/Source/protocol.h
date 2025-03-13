#ifndef __PROTOCOL_H
#define __PROTOCOL_H

#include <stdlib.h>
#include <stdint.h>

#define FIRMWARE_VERSION  (1)                   ///< Version of the firmware
#define SWARM_ID          (0x0000)              ///< Default swarm ID
#define BROADCAST_ADDRESS 0xffffffffffffffffUL  ///< Broadcast address
#define GATEWAY_ADDRESS   0x0000000000000000UL  ///< Gateway address

#define SWRMT_OTA_CHUNK_SIZE        (128U)
#define SWRMT_OTA_SHA256_LENGTH     (32U)

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

typedef struct __attribute__((packed)) {
    swrmt_request_type_t type;
    uint64_t        device_id;
    uint8_t         data[255];
} swrmt_request_t;

typedef struct __attribute__((packed)) {
    uint32_t image_size;                        ///< User image size in bytes
    uint32_t chunk_count;
    uint8_t hash[SWRMT_OTA_SHA256_LENGTH];      ///< SHA256 hash of the firmware
} swrmt_ota_start_pkt_t;

typedef struct __attribute__((packed)) {
    uint32_t index;                             ///< Index of the chunk
    uint8_t  chunk_size;                        ///< Size of the chunk
    uint8_t  chunk[SWRMT_OTA_CHUNK_SIZE];       ///< Bytes array of the firmware chunk
} swrmt_ota_chunk_pkt_t;

typedef struct __attribute__((packed)) {
    uint8_t port;  ///< Port number of the GPIO
    uint8_t pin;   ///< Pin number of the GPIO
    uint8_t value;
} gpio_data_t;

typedef struct __attribute__((packed)) {
    uint32_t timestamp;
    gpio_data_t data;
} swrmt_gpio_event_t;

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
 * @brief   Write the protocol header in a buffer
 *
 * @param[out]  buffer      Bytes array to write to
 * @param[in]   dst         Destination address written in the header
 *
 * @return                  Number of bytes written in the buffer
 */
size_t protocol_header_to_buffer(uint8_t *buffer, uint64_t dst);

/**
 * @brief   Write a TDMA keep alive packet in a buffer
 *
 * @param[out]  buffer      Bytes array to write to
 * @param[in]   dst         Destination address written in the header
 *
 * @return                  Number of bytes written in the buffer
 */
size_t protocol_tdma_keep_alive_to_buffer(uint8_t *buffer, uint64_t dst);

/**
 * @brief   Write a TDMA table update in a buffer
 *
 * @param[out]  buffer      Bytes array to write to
 * @param[in]   dst         Destination address written in the header
 * @param[in]   tdma_table  Pointer to the TDMA table
 *
 * @return                  Number of bytes written in the buffer
 */
size_t protocol_tdma_table_update_to_buffer(uint8_t *buffer, uint64_t dst, protocol_tdma_table_t *tdma_table);

/**
 * @brief   Write a TDMA sync frame in a buffer
 *
 * @param[out]  buffer      Bytes array to write to
 * @param[in]   dst         Destination address written in the header
 * @param[in]   sync_frame  Pointer to the sync frame
 *
 * @return                  Number of bytes written in the buffer
 */
size_t protocol_tdma_sync_frame_to_buffer(uint8_t *buffer, uint64_t dst, protocol_sync_frame_t *sync_frame);

#endif  // __PROTOCOL_H

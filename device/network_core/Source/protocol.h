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

/// Block-OTA (fast OTA) parameters. W = 32 is the largest block the uint32_t
/// received bitmap holds; bigger blocks mean fewer report rounds. Must match the
/// controller's BLOCK_SIZE. The protocol version is echoed in OTA_START_ACK so
/// the controller knows the bootloader speaks the block/bitmap path.
#define SWRMT_OTA_BLOCK_SIZE        (32U)
#define SWRMT_OTA_PROTOCOL_VERSION  (2U)

/// Schema version carried in every SWRMT_MSG_DEVICE_INFO_RESP.
#define SWRMT_DEVICE_INFO_VERSION   (2U)

/// Ceiling for identity strings, including the NUL terminator. Matter
/// (VendorName/ProductName/SerialNumber), Zigbee (ManufacturerName/
/// ModelIdentifier) and Thread (VendorName/VendorModel) all converge on 32.
#define SWRMT_INFO_STRING_LEN       (32U)

/// Bytes of the image SHA256 that travel on the wire. The on-device record
/// keeps all 32; a truncated digest is only ever compared, never trusted as a
/// signature.
#define SWRMT_IMAGE_DIGEST_LEN      (8U)

/// Fixed widths of the site identity a calibration carries.
#define SWRMT_LH2_SITE_NAME_LEN         (16U)   ///< ASCII, NUL-padded, not necessarily NUL-terminated
#define SWRMT_LH2_CALIBRATION_ID_LEN    (8U)    ///< leading bytes of the calibration file's id

/// Image lifecycle, LwM2M Object 5 resource 3 (State).
typedef enum {
    SWRMT_IMAGE_STATE_IDLE = 0,
    SWRMT_IMAGE_STATE_DOWNLOADING = 1,
    SWRMT_IMAGE_STATE_DOWNLOADED = 2,
    SWRMT_IMAGE_STATE_UPDATING = 3,
} swrmt_image_state_t;

/// Outcome of the last image transfer, LwM2M Object 5 resource 5 (Update
/// Result). Only the values this device can actually produce are listed.
typedef enum {
    SWRMT_IMAGE_RESULT_INITIAL = 0,
    SWRMT_IMAGE_RESULT_SUCCESS = 1,
    SWRMT_IMAGE_RESULT_NO_FLASH = 2,
    SWRMT_IMAGE_RESULT_CONN_LOST = 4,
    SWRMT_IMAGE_RESULT_INTEGRITY_FAIL = 5,   // whole-image SHA256 mismatch
    SWRMT_IMAGE_RESULT_UPDATE_FAILED = 8,
} swrmt_image_result_t;

/// Bits of swrmt_device_info_pkt_t.lh2_flags.
#define SWRMT_LH2_FLAG_VALID        (1U << 0)   // a usable homography set is loaded
#define SWRMT_LH2_FLAG_FROM_FLASH   (1U << 1)   // it came from the provisioned config page

typedef enum {
    SWRMT_DEVICE_TYPE_UNKNOWN = 0,
    SWRMT_DEVICE_TYPE_DOTBOTV3 = 1,
    SWRMT_DEVICE_TYPE_DOTBOTV2 = 2,
    SWRMT_DEVICE_TYPE_NRF5340DK = 3,
} swrmt_device_type_t;

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
    SWRMT_MSG_OTA_CHUNK_ACK = 0x87,          // retired with the per-chunk OTA path; id kept reserved
    SWRMT_MSG_GPIO_EVENT = 0x88,
    SWRMT_MSG_LOG_EVENT = 0x89,
    SWRMT_MSG_OTA_BLOCK_REPORT_REQ = 0x8A,   // host -> device: request received bitmap
    SWRMT_MSG_OTA_BLOCK_REPORT_RESP = 0x8B,  // device -> host: received bitmap for a block
    SWRMT_MSG_OTA_FINALIZE = 0x8C,           // host -> device: verify whole-image SHA256
    SWRMT_MSG_OTA_FINALIZE_RESP = 0x8D,      // device -> host: image SHA256 match result
    SWRMT_MSG_REQUEST_MESSAGE = 0x8E,        // host -> device: emit one message once
    SWRMT_MSG_DEVICE_INFO_RESP = 0x8F,       // device -> host: what this bot is running
    // FIXME: we need better namespacing for these messages, for example,
    // use 0x80 for SwarmIT application type, and then use an internal namespace for SwarmIT messages,
    // like 0x80.0x01 for SwarmIT status, 0x80.0x02 for SwarmIT start, etc.
    // for the moment, I am just appending SWRMT_MSG_LH2_CALIBRATION after SWRMT_MESSAGE.
    SWRMT_MESSAGE = 0xA0, // custom message type
    SWRMT_MSG_LH2_CALIBRATION = 0xA1,
    SWRMT_MSG_LH2_CAPTURE = 0xA2, // host -> node: capture one raw LH2 sample (READY mode only). DEPRECATED: the calibrate app replaces it.
} swrmt_message_type_t;

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
    swrmt_message_type_t    type;
    uint8_t                 data[255];
} swrmt_request_t;

/// Read with a pointer cast from a buffer that may be shorter than this struct:
/// name and version were appended after the fact, so check the received length
/// before touching them (the same tolerance that let `version` be appended).
typedef struct __attribute__((packed)) {
    uint32_t image_size;                        ///< User image size in bytes
    uint32_t chunk_count;
    uint8_t  version;                           ///< OTA protocol version (2 = block; absent/other = legacy)
    char     image_name[SWRMT_INFO_STRING_LEN];     ///< LwM2M Object 5 res 6 PkgName, display only
    char     image_version[SWRMT_INFO_STRING_LEN];  ///< LwM2M Object 5 res 7 PkgVersion, display only
} swrmt_ota_start_pkt_t;

/// Bytes a controller must send for image_name/image_version to be present.
#define SWRMT_OTA_START_NAMED_SIZE  (sizeof(swrmt_ota_start_pkt_t))

/// Generic one-shot query. Modelled on MAVLink's MAV_CMD_REQUEST_MESSAGE
/// (512), which superseded ~15 bespoke MAV_CMD_REQUEST_* commands: a future
/// query adds a msg_id here rather than a new message pair.
typedef struct __attribute__((packed)) {
    uint8_t msg_id;                             ///< which message to emit once
    uint8_t flags;                              ///< reserved (response target); must be 0
} swrmt_request_message_pkt_t;

/// Inventory the host reads once and caches, refreshed when info_gen changes.
/// Field names follow LwM2M Object 5 and Matter General Diagnostics so a
/// gateway-side bridge to either is a field mapping rather than a redesign.
typedef struct __attribute__((packed)) {
    uint8_t  info_version;                          ///< schema version of this message
    uint8_t  info_gen;                              ///< echoes the status counter (detects an in-flight change)
    uint32_t boot_count;                            ///< Matter RebootCount, widened to u32 (a bot reboots per experiment)
    uint32_t uptime_s;                              ///< Matter UpTime, narrowed to u32 (136 years)
    char     bl_version[SWRMT_INFO_STRING_LEN];     ///< bootloader   git describe --always --dirty
    char     net_version[SWRMT_INFO_STRING_LEN];    ///< network core git describe --always --dirty
    uint8_t  image_state;                           ///< swrmt_image_state_t
    uint8_t  image_result;                          ///< swrmt_image_result_t
    uint32_t image_size;                            ///< bytes, as flashed
    uint8_t  image_digest[SWRMT_IMAGE_DIGEST_LEN];  ///< first bytes of the image SHA256; the machine-comparable identity
    char     image_name[SWRMT_INFO_STRING_LEN];     ///< LwM2M Object 5 res 6 PkgName, display only
    char     image_version[SWRMT_INFO_STRING_LEN];  ///< LwM2M Object 5 res 7 PkgVersion, display only
    uint8_t  lh2_homography_count;                  ///< 0 = uncalibrated
    uint8_t  lh2_flags;                             ///< SWRMT_LH2_FLAG_*
    char     lh2_site_name[SWRMT_LH2_SITE_NAME_LEN];            ///< site of the loaded calibration, all zero if none
    uint8_t  lh2_calibration_id[SWRMT_LH2_CALIBRATION_ID_LEN];  ///< id of the loaded calibration, all zero if none
} swrmt_device_info_pkt_t;

_Static_assert(sizeof(swrmt_device_info_pkt_t) == 178,
               "swrmt_device_info_pkt_t is a wire format; its size is part of the contract");

typedef struct __attribute__((packed)) {
    uint32_t index;                             ///< Index of the chunk
    uint8_t  chunk_size;                        ///< Size of the chunk
    uint8_t  sha[8];
    uint8_t  chunk[SWRMT_OTA_CHUNK_SIZE];       ///< Bytes array of the firmware chunk
} swrmt_ota_chunk_pkt_t;

typedef struct __attribute__((packed)) {
    uint32_t block_index;                       ///< Block the controller is asking about
    uint8_t  block_size;                        ///< Chunks per block (W)
} swrmt_ota_block_report_req_pkt_t;

typedef struct __attribute__((packed)) {
    uint32_t block_index;                       ///< Block the device currently holds
    uint32_t received_mask;                     ///< Bit i set: chunk block_index*W+i written
    uint8_t  status;                            ///< Reserved (0)
} swrmt_ota_block_report_resp_pkt_t;

typedef struct __attribute__((packed)) {
    uint8_t  sha[SWRMT_OTA_SHA256_LENGTH];      ///< Expected SHA256 of the whole image
} swrmt_ota_finalize_pkt_t;

typedef struct __attribute__((packed)) {
    uint8_t  ok;                                ///< 1 if the image SHA256 matched
} swrmt_ota_finalize_resp_pkt_t;

typedef struct __attribute__((packed)) {
    uint32_t homography_count;              ///< number of homography matrices used for localization
    uint32_t homography_index;              ///< index of the homography matrix to use for localization
    float    homography[3][3];              ///< homography matrix for localization, float32 in mm
    uint32_t valid_mm[4];                   ///< x_min, y_min, x_max, y_max of plausible positions, in mm
    char     site_name[SWRMT_LH2_SITE_NAME_LEN];
    uint8_t  calibration_id[SWRMT_LH2_CALIBRATION_ID_LEN];
} swrmt_lh2_calibration_data_t;

_Static_assert(sizeof(swrmt_lh2_calibration_data_t) == 84,
               "swrmt_lh2_calibration_data_t is a wire format; its size is part of the contract");

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

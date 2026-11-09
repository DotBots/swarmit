#ifndef __LH2_SESSION_H
#define __LH2_SESSION_H

/**
 * @brief   The LH2 calibration push as a session keyed by calibration id and station mask
 *
 * A push is one 0xA3 message per station of its mask. Messages of one push
 * fill their slots in any order and any number of times; a message carrying
 * another id or mask starts a new session and drops what the old one held, so
 * two solves never mix. The push is complete when every bit of the mask has
 * arrived. The session lives in RAM only, so a reboot discards a half push.
 *
 * No hardware calls, so the module also builds on the host.
 *
 * @{
 * @file
 * @copyright Inria, 2026
 * @}
 */

#include <stdbool.h>
#include <stdint.h>

#include "protocol.h"

typedef struct {
    bool     open;                                  ///< a push is being received
    uint32_t mask;                                  ///< stations of that push
    uint32_t received;                              ///< stations whose message has arrived
    uint8_t  id[SWRMT_LH2_CALIBRATION_ID_LEN];      ///< calibration id of that push
} lh2_session_t;

typedef enum {
    LH2_SESSION_DROPPED,    ///< malformed: nothing changed
    LH2_SESSION_STORED,     ///< slot written, push not complete yet
    LH2_SESSION_COMPLETE,   ///< slot written and every station of the mask has arrived
} lh2_session_result_t;

/**
 * @brief   Take one calibration message into the session and the slot arrays
 *
 * Opening a session zeroes every slot of both arrays.
 *
 * @param[in,out]   session         Session state
 * @param[in]       msg             The message
 * @param[in,out]   homographies    Slots, by station index
 * @param[in,out]   valid_mm        Rectangles, by station index
 *
 * @return  what was done
 */
lh2_session_result_t lh2_session_receive(lh2_session_t *session, const swrmt_lh2_calibration_data_t *msg,
                                         float homographies[SWRMT_LH2_STATIONS][3][3], uint32_t valid_mm[SWRMT_LH2_STATIONS][4]);

#endif

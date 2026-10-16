/**
 * @file
 * @brief  The LH2 calibration push session
 *
 * @copyright Inria, 2026
 */
#include <string.h>

#include "lh2_session.h"

lh2_session_result_t lh2_session_receive(lh2_session_t *session, const swrmt_lh2_calibration_data_t *msg,
                                         float homographies[SWRMT_LH2_STATIONS][3][3], uint32_t valid_mm[SWRMT_LH2_STATIONS][4]) {
    uint32_t mask  = msg->station_mask;
    uint32_t index = msg->station_index;
    if (mask == 0 || (mask >> SWRMT_LH2_STATIONS) != 0 || index >= SWRMT_LH2_STATIONS || ((mask >> index) & 1U) == 0) {
        return LH2_SESSION_DROPPED;
    }

    if (!session->open || session->mask != mask || memcmp(session->id, msg->calibration_id, sizeof(session->id)) != 0) {
        session->open     = true;
        session->mask     = mask;
        session->received = 0;
        memcpy(session->id, msg->calibration_id, sizeof(session->id));
        memset(homographies, 0, SWRMT_LH2_STATIONS * sizeof(homographies[0]));
        memset(valid_mm, 0, SWRMT_LH2_STATIONS * sizeof(valid_mm[0]));
    }

    memcpy(homographies[index], msg->homography, sizeof(homographies[0]));
    memcpy(valid_mm[index], msg->valid_mm, sizeof(valid_mm[0]));
    session->received |= 1U << index;
    return (session->received == session->mask) ? LH2_SESSION_COMPLETE : LH2_SESSION_STORED;
}

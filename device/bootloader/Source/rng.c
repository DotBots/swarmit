/**
 * @file
 * @ingroup bsp_rng
 *
 * @brief  nrf5340-app-specific definition of the "rng" bsp module.
 *
 * @author Alexandre Abadie <alexandre.abadie@inria.fr>
 *
 * @copyright Inria, 2023
 */
#include <nrf.h>
#include <stdbool.h>
#include <stdint.h>

#include "ipc.h"
#include "rng.h"

//========================== variables =========================================

extern volatile __attribute__((section(".shared_data"))) ipc_shared_data_t ipc_shared_data;

//=========================== public ===========================================

void rng_init(void) {
    ipc_network_call(IPC_RNG_INIT_REQ);
}

void rng_read(uint8_t *value) {
    ipc_network_call(IPC_RNG_READ_REQ);
    *value = ipc_shared_data.rng.value;
}

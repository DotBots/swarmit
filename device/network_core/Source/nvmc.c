/**
 * @file
 * @ingroup bsp_nvmc
 *
 * @brief  Implementation of the "nvmc" bsp module.
 *
 * @author Alexandre Abadie <alexandre.abadie@inria.fr>
 *
 * @copyright Inria, 2023
 */

#include <stdlib.h>
#include <stdint.h>

#include <nrf.h>
#include "nvmc.h"

//=========================== public ==========================================

void nvmc_page_erase(uint32_t page) {
    const uint32_t *addr = (const uint32_t *)(FLASH_OFFSET + page * FLASH_PAGE_SIZE);

    NRF_NVMC_NS->CONFIG = (NVMC_CONFIG_WEN_Een << NVMC_CONFIG_WEN_Pos);
    while (!NRF_NVMC_NS->READY) {}
    *(uint32_t *)addr  = 0xFFFFFFFF;
    while (!NRF_NVMC_NS->READY) {}
}

void nvmc_write(const uint32_t *addr, const void *data, size_t len) {
    uint32_t       *dest_addr = (uint32_t *)addr;
    const uint32_t *data_addr = data;

    NRF_NVMC_NS->CONFIG = (NVMC_CONFIG_WEN_Wen << NVMC_CONFIG_WEN_Pos);
    for (uint32_t i = 0; i < (len >> 2); i++) {
        while (!NRF_NVMC_NS->READY) {}
        *dest_addr++ = data_addr[i];
    }
    while (!NRF_NVMC_NS->READY) {}
    NRF_NVMC_NS->CONFIG = (NVMC_CONFIG_WEN_Ren << NVMC_CONFIG_WEN_Pos);
}

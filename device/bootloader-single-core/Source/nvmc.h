#ifndef __NVMC_H
#define __NVMC_H

#include <stdlib.h>
#include <stdint.h>

//=========================== defines ==========================================

#define FLASH_PAGE_SIZE 4096
#define FLASH_OFFSET 0x0

//=========================== public ===========================================

void nvmc_page_erase(uint32_t page);
void nvmc_write(const uint32_t *addr, const void *input, size_t len);

#endif

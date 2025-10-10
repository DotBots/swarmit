/**
 * @file
 * @author  Alexandre Abadie <alexandre.abadie@inria.fr>
 * @brief   Fault handlers implementations
 *
 * Adapted from @url https://wiki.segger.com/Cortex-M_Fault
 *
 * @copyright Inria, 2024
 *
 */

#include <nrf.h>
#include "fault_handlers.h"

void HardFaultHandler(uint32_t *sp) {
    if (SCB->HFSR & (SCB_HFSR_DEBUGEVT_Msk)) {
        SCB->HFSR |=  (SCB_HFSR_DEBUGEVT_Msk);      // Reset Hard Fault status
        *(sp + 6u) += 2u;                           // PC is located on stack at SP + 24 bytes. Increment PC by 2 to skip break instruction.
        return;                                     // Return to interrupted application
    }
#if defined(DEBUG)
    hardfault_regs.shcsr.word    = SCB->SHCSR;  // System Handler Control and State Register
    hardfault_regs.mmfsr.byte    = (uint8_t)(SCB->SHCSR & 0xFF);   // MemManage Fault Status Register
    hardfault_regs.mmfar         = SCB->MMFAR;  // MemManage Fault Address Register
    hardfault_regs.bfsr.byte     = (uint8_t)((SCB->SHCSR & 0xFF00) >> 8);    // Bus Fault Status Register
    hardfault_regs.bfar          = SCB->BFAR;   // Bus Fault Manage Address Register
    hardfault_regs.ufsr.halfword = (uint16_t)(SCB->SHCSR >> 16);    // Usage Fault Status Register
    hardfault_regs.hfsr.word     = SCB->HFSR;   // Hard Fault Status Register
    hardfault_regs.dfsr.word     = SCB->DFSR;   // Debug Fault Status Register
    hardfault_regs.afsr          = SCB->AFSR;   // Auxiliary Fault Status Register
    hardfault_regs.regs.r0       = sp[0];       // Register R0
    hardfault_regs.regs.r1       = sp[1];       // Register R1
    hardfault_regs.regs.r2       = sp[2];       // Register R2
    hardfault_regs.regs.r3       = sp[3];       // Register R3
    hardfault_regs.regs.r12      = sp[4];       // Register R12
    hardfault_regs.regs.lr       = sp[5];       // Link register LR
    hardfault_regs.regs.pc       = sp[6];       // Program counter PC
    hardfault_regs.regs.psr.word = sp[7];       // Program status word PSR
#else
    (void)sp;
#endif
    while (1) {
        __NOP();
    }
}

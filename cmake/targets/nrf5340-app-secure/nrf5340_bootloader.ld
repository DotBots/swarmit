/*
 * GNU ld linker script for the swarmit secure bootloader on
 * nRF5340 app core. Translates SES MemoryMap.xml + flash_placement.xml
 * for the bootloader-app target.
 *
 * Memory layout:
 *   FLASH1   0x00000000   65280 B   ← bootloader code (≈63.75 KiB)
 *   NSC_FLASH 0x0000FF00   256 B    ← NSC veneer (gnu.sgstubs section)
 *   RAM1     0x20000000    32 KiB   ← bootloader RAM (secure side)
 *   RAM2     0x20040000   255 KiB   ← available to secure side (unused)
 *
 * The .gnu.sgstubs section at 0x0000FF00 is where gcc-arm-none-eabi
 * places the cmse_nonsecure_entry veneers. NS apps call into this
 * region; addresses must remain stable across bootloader rebuilds so
 * existing NS apps don't need re-linking.
 *
 * Pinned: .shared_data at 0x20004000 (IPC region — same as elsewhere).
 */

MEMORY
{
    FLASH      (rx)  : ORIGIN = 0x00000000, LENGTH = 0xFF00     /* 65280 B */
    NSC_FLASH  (rx)  : ORIGIN = 0x0000FF00, LENGTH = 256
    RAM        (rwx) : ORIGIN = 0x20000000, LENGTH = 32K
}

ENTRY(Reset_Handler)

__STACKSIZE__         = 8K;
__STACKSIZE_PROCESS__ = 0;
__HEAPSIZE__          = 0;

__shared_data_addr__  = 0x20004000;

SECTIONS
{
    /* ── FLASH ─────────────────────────────────────────────────── */

    .vectors :
    {
        KEEP(*(.vectors))
        KEEP(*(.isr_vector))
    } > FLASH

    .text :
    {
        __text_start__ = .;
        *(.text*)
        *(.init)
        *(.init_rodata)
        . = ALIGN(4);
        __text_end__ = .;
    } > FLASH
    __text_load_start__ = LOADADDR(.text);

    .rodata :
    {
        *(.rodata*)
        . = ALIGN(4);
    } > FLASH

    /* gcc-arm-none-eabi places cmse_nonsecure_entry veneers here. */
    .gnu.sgstubs :
    {
        __sg_start__ = .;
        *(.gnu.sgstubs*)
        __sg_end__ = .;
    } > NSC_FLASH

    /* ── Initialized data: copied flash → RAM by Reset_Handler ──── */

    .data :
    {
        . = ALIGN(4);
        __data_start__ = .;
        *(.data*)
        *(.data_run)
        . = ALIGN(4);
        __data_end__ = .;
    } > RAM AT > FLASH
    __data_load_start__ = LOADADDR(.data);

    .fast :
    {
        . = ALIGN(4);
        __fast_start__ = .;
        *(.fast*)
        *(.fast_run)
        . = ALIGN(4);
        __fast_end__ = .;
    } > RAM AT > FLASH
    __fast_load_start__ = LOADADDR(.fast);

    .ctors :
    {
        . = ALIGN(4);
        __ctors_start__ = .;
        KEEP(*(SORT(.ctors.*)))
        KEEP(*(.ctors))
        __ctors_end__ = .;
    } > RAM AT > FLASH
    __ctors_load_start__ = LOADADDR(.ctors);

    .dtors :
    {
        . = ALIGN(4);
        __dtors_start__ = .;
        KEEP(*(SORT(.dtors.*)))
        KEEP(*(.dtors))
        __dtors_end__ = .;
    } > RAM AT > FLASH
    __dtors_load_start__ = LOADADDR(.dtors);

    __rodata_start__       = .;
    __rodata_end__         = .;
    __rodata_load_start__  = .;

    .tdata :
    {
        . = ALIGN(4);
        __tdata_start__ = .;
        *(.tdata*)
        *(.tdata_run)
        . = ALIGN(4);
        __tdata_end__ = .;
    } > RAM AT > FLASH
    __tdata_load_start__ = LOADADDR(.tdata);

    /* ── Uninitialized data ────────────────────────────────────── */

    .bss (NOLOAD) :
    {
        . = ALIGN(4);
        __bss_start__ = .;
        *(.bss*)
        *(COMMON)
        . = ALIGN(4);
        __bss_end__ = .;
    } > RAM

    .tbss (NOLOAD) :
    {
        . = ALIGN(4);
        __tbss_start__ = .;
        *(.tbss*)
        __tbss_end__ = .;
    } > RAM

    .shared_data __shared_data_addr__ (NOLOAD) :
    {
        __shared_data_start__ = .;
        KEEP(*(.shared_data))
        . = ALIGN(4);
        __shared_data_end__ = .;
    } > RAM

    /* ── Heap (empty) ─────────────────────────────────────────── */

    .heap (NOLOAD) :
    {
        . = ALIGN(8);
        __heap_start__ = .;
        . = . + __HEAPSIZE__;
        __heap_end__ = .;
    } > RAM

    PROVIDE(end  = __heap_start__);
    PROVIDE(_end = __heap_start__);

    .stack_process (NOLOAD) :
    {
        . = ALIGN(8);
        __stack_process_start__ = .;
        . = . + __STACKSIZE_PROCESS__;
        __stack_process_end__ = .;
    } > RAM

    .stack ORIGIN(RAM) + LENGTH(RAM) - __STACKSIZE__ (NOLOAD) :
    {
        . = ALIGN(8);
        __stack_start__ = .;
        . = . + __STACKSIZE__;
        __stack_end__ = .;
    } > RAM

    /DISCARD/ :
    {
        *(.ARM.exidx*)
        *(.ARM.extab*)
    }
}

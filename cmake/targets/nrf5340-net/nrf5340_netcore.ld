/*
 * GNU ld linker script for the swarmit netcore firmware on
 * nRF5340 net core (Cortex-M33 SOFT FLOAT — no FPU).
 *
 * Translates SES MemoryMap.xml for the netcore-app target.
 *
 * Memory layout:
 *   FLASH1   0x01000000   254 KiB   ← netcore flash (2 KiB reserved at end)
 *   RAM1     0x21000000    64 KiB   ← netcore-dedicated RAM
 *
 * No NSC region — net core does not have TrustZone partitioning of its
 * own flash; secure-vs-NS is an app-core concept. Net core gets its
 * own SPU rules applied from the app-core bootloader.
 */

MEMORY
{
    FLASH (rx)  : ORIGIN = 0x01000000, LENGTH = 254K
    RAM   (rwx) : ORIGIN = 0x21000000, LENGTH = 64K
}

ENTRY(Reset_Handler)

__STACKSIZE__         = 8K;
__STACKSIZE_PROCESS__ = 0;
__HEAPSIZE__          = 0;

SECTIONS
{
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

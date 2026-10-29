// Host test of the DS18B20 driver against a simulated 1-Wire bus: CRC, ROM search with several probes,
// match ROM, temperature conversion, error paths. Run: test_host/run.sh
#include <math.h>
#include <stdio.h>
#include <string.h>
#include "../main/ds18b20.c"   // includes the static functions (crc8, search_next)

static int failures;
#define CHECK(cond) do { if (!(cond)) { printf("FAIL line %d: %s\n", __LINE__, #cond); failures++; } } while (0)

// Simulated probes. The bus is wired-AND: a bit reads 0 if any talking probe sends 0.
typedef struct {
    uint8_t rom[8];
    uint8_t sp[9];          // scratchpad as the probe would send it
    int16_t raw_measured;   // what a conversion puts into the scratchpad
    bool active;            // still taking part after search / match ROM
} fake_probe;

static fake_probe probes[4];
static int n_probes;
static bool line_stuck_low;
static int delayed_ticks;
static uint8_t func_cmds[8];
static int n_func_cmds;

enum { ST_IDLE, ST_ROM_CMD, ST_SEARCH, ST_MATCH, ST_FUNC_CMD, ST_READ_SP };
static int state;
static uint8_t shift;                       // bits of the command byte being received
static int nbits;                           // bits received (command) or ROM bit position (search, match)
static int search_phase;                    // 0: send bit, 1: send complement, 2: receive direction

void vTaskDelay(TickType_t ticks) { delayed_ticks += ticks; }
esp_err_t ow_init(int gpio) { CHECK(gpio == 4); return ESP_OK; }

static bool rom_bit(const fake_probe *p, int n) { return (p->rom[n / 8] >> (n % 8)) & 1; }

static void set_scratch(fake_probe *p, int16_t raw)
{
    uint8_t sp[9] = {(uint8_t)raw, (uint8_t)(raw >> 8), 0x4B, 0x46, 0x7F, 0xFF, 0x0C, 0x10, 0};
    sp[8] = crc8(sp, 8);
    memcpy(p->sp, sp, 9);
}

static void add_probe(uint8_t family, uint64_t serial, int16_t raw_measured)
{
    fake_probe *p = &probes[n_probes++];
    p->rom[0] = family;
    for (int i = 0; i < 6; i++) p->rom[1 + i] = (uint8_t)(serial >> (8 * i));
    p->rom[7] = crc8(p->rom, 7);
    p->raw_measured = raw_measured;
    set_scratch(p, RAW_POWER_ON);
}

esp_err_t ow_reset(void)
{
    if (line_stuck_low) return ESP_FAIL;
    state = ST_ROM_CMD; shift = 0; nbits = 0;
    for (int i = 0; i < n_probes; i++) probes[i].active = false;
    return n_probes > 0 ? ESP_OK : ESP_ERR_NOT_FOUND;
}

static void command_byte_done(void)
{
    if (state == ST_ROM_CMD) {
        for (int i = 0; i < n_probes; i++) probes[i].active = true;
        state = shift == CMD_SEARCH_ROM ? ST_SEARCH : shift == CMD_MATCH_ROM ? ST_MATCH
              : shift == CMD_SKIP_ROM ? ST_FUNC_CMD : ST_IDLE;
        search_phase = 0;
    } else {
        func_cmds[n_func_cmds++] = shift;
        state = ST_IDLE;
        if (shift == CMD_CONVERT_T) {
            for (int i = 0; i < n_probes; i++) {
                if (probes[i].active) set_scratch(&probes[i], probes[i].raw_measured);
            }
        } else if (shift == CMD_READ_SCRATCH) {
            state = ST_READ_SP;
        }
    }
    shift = 0; nbits = 0;
}

void ow_write_bit(bool bit)
{
    if (state == ST_ROM_CMD || state == ST_FUNC_CMD) {
        if (bit) shift |= (uint8_t)(1 << nbits);
        if (++nbits == 8) command_byte_done();
    } else if (state == ST_SEARCH || state == ST_MATCH) {
        CHECK(state == ST_MATCH || search_phase == 2);   // direction only after bit + complement
        for (int i = 0; i < n_probes; i++) {
            if (probes[i].active && rom_bit(&probes[i], nbits) != bit) probes[i].active = false;
        }
        search_phase = 0;
        if (++nbits == 64) { state = ST_FUNC_CMD; nbits = 0; shift = 0; }
    }
}

bool ow_read_bit(void)
{
    bool level = true;                      // released line reads 1
    if (state == ST_SEARCH && search_phase < 2) {
        for (int i = 0; i < n_probes; i++) {
            if (probes[i].active && rom_bit(&probes[i], nbits) == (search_phase == 1)) level = false;
        }
        search_phase++;
    } else if (state == ST_READ_SP && nbits < 72) {
        for (int i = 0; i < n_probes; i++) {
            if (probes[i].active && !((probes[i].sp[nbits / 8] >> (nbits % 8)) & 1)) level = false;
        }
        nbits++;
    }
    return level;
}

static void reset_bus(void)
{
    n_probes = 0; line_stuck_low = false; delayed_ticks = 0; n_func_cmds = 0; state = ST_IDLE;
}

static bool contains(uint8_t roms[][8], int n, const uint8_t rom[8])
{
    for (int i = 0; i < n; i++) {
        if (memcmp(roms[i], rom, 8) == 0) return true;
    }
    return false;
}

int main(void)
{
    // 1. CRC: check value of CRC-8/MAXIM-DOW over "123456789" is 0xA1 (reveng CRC catalogue)
    CHECK(crc8((const uint8_t *)"123456789", 9) == 0xA1);
    // An unanswered read gives all ones; their CRC must not look valid
    const uint8_t ones[8] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
    CHECK(crc8(ones, 8) != 0xFF);

    // 2. Search: three probes whose ROMs differ at early, middle and late bits are each found once
    uint8_t roms[4][8];
    reset_bus();
    add_probe(0x28, 0x000000000001ULL, 0);
    add_probe(0x28, 0x000000000002ULL, 0);
    add_probe(0x28, 0x800000000001ULL, 0);
    CHECK(ds18b20_init(4, roms, 4) == 3);
    for (int i = 0; i < 3; i++) CHECK(contains(roms, 3, probes[i].rom));
    CHECK(memcmp(roms[0], roms[1], 8) != 0 && memcmp(roms[1], roms[2], 8) != 0
          && memcmp(roms[0], roms[2], 8) != 0);

    // 3. Search stops at `max`
    CHECK(ds18b20_init(4, roms, 2) == 2);

    // 4. One probe; a device of another family (0x10 = DS18S20) is skipped
    reset_bus();
    add_probe(0x28, 0x123456789ABCULL, 0);
    CHECK(ds18b20_init(4, roms, 4) == 1);
    CHECK(memcmp(roms[0], probes[0].rom, 8) == 0);
    reset_bus();
    add_probe(0x10, 0x000000000001ULL, 0);
    add_probe(0x28, 0x000000000002ULL, 0);
    CHECK(ds18b20_init(4, roms, 4) == 1);
    CHECK(memcmp(roms[0], probes[1].rom, 8) == 0);

    // 5. Empty bus and a line held low find nothing
    reset_bus();
    CHECK(ds18b20_init(4, roms, 4) == 0);
    reset_bus();
    add_probe(0x28, 1, 0);
    line_stuck_low = true;
    CHECK(ds18b20_init(4, roms, 4) == 0);

    // 6. Before any conversion the register holds 85 °C, which is reported as an error, not a value
    reset_bus();
    add_probe(0x28, 0x000000000001ULL, 0x0191);
    add_probe(0x28, 0x000000000002ULL, (int16_t)0xFF5E);
    add_probe(0x28, 0x800000000001ULL, (int16_t)0xFC90);
    float t = 0;
    CHECK(ds18b20_read(probes[0].rom, &t) == ESP_ERR_INVALID_STATE);

    // 7. Convert: Skip ROM + Convert T, waits >= 750 ms; then match ROM reads each probe's own value.
    //    Values from the DS18B20 datasheet temperature/data table.
    n_func_cmds = 0;
    CHECK(ds18b20_convert_all() == ESP_OK);
    CHECK(n_func_cmds == 1 && func_cmds[0] == CMD_CONVERT_T);
    CHECK(delayed_ticks >= 75);
    CHECK(ds18b20_read(probes[0].rom, &t) == ESP_OK && fabsf(t - 25.0625f) < 1e-4f);
    CHECK(ds18b20_read(probes[1].rom, &t) == ESP_OK && fabsf(t - -10.125f) < 1e-4f);
    CHECK(ds18b20_read(probes[2].rom, &t) == ESP_OK && fabsf(t - -55.0f) < 1e-4f);

    // 8. More table rows through the same path: +125, +0.5, 0, -0.5, -25.0625 °C
    const int16_t raws[] = {0x07D0, 0x0008, 0x0000, (int16_t)0xFFF8, (int16_t)0xFE6F};
    const float temps[] = {125.0f, 0.5f, 0.0f, -0.5f, -25.0625f};
    for (int i = 0; i < 5; i++) {
        set_scratch(&probes[0], raws[i]);
        CHECK(ds18b20_read(probes[0].rom, &t) == ESP_OK && fabsf(t - temps[i]) < 1e-4f);
    }

    // 9. Corrupted scratchpad byte is rejected
    set_scratch(&probes[0], 0x0191);
    probes[0].sp[0] ^= 0x01;
    CHECK(ds18b20_read(probes[0].rom, &t) == ESP_ERR_INVALID_CRC);

    // 10. A probe that has gone (ROM not on the bus) while others still answer: nobody talks, all ones
    uint8_t gone[8] = {0x28, 9, 9, 9, 9, 9, 9, 0};
    gone[7] = crc8(gone, 7);
    CHECK(ds18b20_read(gone, &t) == ESP_ERR_INVALID_CRC);

    // 11. Empty bus on read
    reset_bus();
    CHECK(ds18b20_read(gone, &t) == ESP_ERR_NOT_FOUND);

    printf(failures ? "%d check(s) failed\n" : "OK: all DS18B20 host checks passed\n", failures);
    return failures != 0;
}

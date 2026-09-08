#include <SPI.h>
// #define ESP_Abeast_ID      2     
#define ESP_Abeast_ID      3     
/* =================== Broches & constantes =================== */
const int CS_PIN_0    = 5;
const int CS_PIN_1    = 4;
const int CS_PIN_2    = 0;
const int CS_PIN_FLASH= 2;   // pas utilisé ici mais laissé en HIGH
const int MUX_A0      = 16;
const int MUX_A1      = 15;
const int LED_PIN     = LED_BUILTIN;

#define NUM_ABEAST                 3
#define NUM_COUNTERS_PER_ABEAST    3
#define BAUD_RATE                  115200

// Reg 8 bitfield (d’après ton tableau: bit7=rst_c, bit4=gx2, bit2=cs_sh, bit1=cs_pre, bit0=bdgp)
static const uint8_t REG8_RST_C_BIT = 7;

/* =================== Config par défaut =================== */
struct ABeastConfig {
  uint8_t vpre_bias;     // reg 0
  uint8_t sh_vcm;        // reg 1
  uint8_t sh_timebias;   // reg 2
  uint8_t vth_baseline;  // reg 3
  uint8_t comp_vth_0;    // reg 4
  uint8_t comp_vth_1;    // reg 5
  uint8_t comp_vth_2;    // reg 6
  uint8_t reg_8;         // reg 8 (bitfield)
};
// // <<< AB1 Config>>>
// const ABeastConfig DEFAULT_CFG[NUM_ABEAST] = {
//   {124, 194, 115, 96, 227, 201, 178, 13}, // ABeast_1
//   {124, 194, 115, 88, 215, 174,  149, 13}, // ABeast_2
//   {124, 194, 115, 91, 212, 178,  154, 13}  // ABeast_3
// };
// <<< AB2 Config>>>
// const ABeastConfig DEFAULT_CFG[NUM_ABEAST] = {
//   {124, 194, 115, 98, 230, 198, 175, 13}, // ABeast_1
//   {124, 194, 115, 98, 234, 203,187, 13}, // ABeast_2
//   {124, 194, 115, 89, 234, 210,186, 13}  // ABeast_3
// };
//Valeurs config pour espabeast 3
const ABeastConfig DEFAULT_CFG[NUM_ABEAST] = {
  // ABeast_1
  {124, 194, 115, 96, 230, 205, 200, 13},
  // ABeast_2
  {124, 194, 115, 88, 235, 200, 189, 13},
  // ABeast_3
  {124, 194, 115, 101, 235, 205, 190, 13}
};
/* =================== SPI vers ABeast =================== */
static inline int chipToCS(int chip){
  switch (chip) {
    case 0: return CS_PIN_0;
    case 1: return CS_PIN_1;
    case 2: return CS_PIN_2;
    default: return CS_PIN_0;
  }
}

// Transaction SPI : 2 MHz, MODE1
SPISettings abeastSPISettings(2000000, MSBFIRST, SPI_MODE1);

// lecture/écriture registre
char read_write_reg(char chip, char address, char value, bool read) {
  uint16_t var1 = (read ? (uint16_t(address) << 8) | value
                        : (uint16_t(address | 0x80) << 8) | value);
  char receivedVal = 0;

  SPI.beginTransaction(abeastSPISettings);
  int cs = chipToCS(chip);
  digitalWrite(cs, LOW);
  delayMicroseconds(30);
  receivedVal = SPI.transfer16(var1);
  delayMicroseconds(30);
  digitalWrite(cs, HIGH);
  SPI.endTransaction();

  return receivedVal;
}

static inline void writeRegAB(uint8_t chip, uint8_t addr, uint8_t val){
  read_write_reg((char)chip, (char)addr, (char)val, /*read=*/false);
  delay(2);
}
static inline uint8_t readRegAB(uint8_t chip, uint8_t addr){
  return (uint8_t)read_write_reg((char)chip, (char)addr, 0x00, /*read=*/true);
}

/* =================== MUX / ENABLE =================== */
/*
 * Rappel hardware :
 *  - ENABLE = OR(MUX_A0, MUX_A1) via 74LVC1G32
 *  - channel 0 -> A1=0, A0=0 -> ENABLE=0 -> VDDA + AOP OFF
 *  - channel 1,2,3 -> au moins un à 1 -> ENABLE=1 -> VDDA + AOP ON
 */
void setMuxBits(bool a1, bool a0) {
  digitalWrite(MUX_A0, a0 ? HIGH : LOW);
  digitalWrite(MUX_A1, a1 ? HIGH : LOW);

  Serial.printf("MUX bits: A1=%d A0=%d  (ENABLE=%s)\n",
                a1 ? 1 : 0,
                a0 ? 1 : 0,
                (a1 || a0) ? "ON (analog ON)" : "OFF (analog OFF)");
}

// compatibilité : version "canal" 0..3 si tu veux encore l'utiliser
void setMuxChannel(uint8_t channel) {
  bool a0 = (channel & 0x01) != 0;
  bool a1 = (channel & 0x02) != 0;
  setMuxBits(a1, a0);
  Serial.printf("MUX channel=%u -> A1=%d A0=%d\n",
                channel, a1 ? 1 : 0, a0 ? 1 : 0);
}

// sélection lisible d'un ABeast
void selectAbeast(uint8_t abe) {
  switch (abe) {
    case 0: // ABeast0 -> 01
      setMuxBits(false, true);   // A1=0, A0=1
      break;
    case 1: // ABeast1 -> 10
      setMuxBits(true,  false);  // A1=1, A0=0
      break;
    case 2: // ABeast2 -> 11
      setMuxBits(true,  true);   // A1=1, A0=1
      break;
    default: // sécurité : tout couper
      setMuxBits(false, false);  // 00
      break;
  }
  Serial.printf("Selected ABeast%d\n", abe);
}

void printConfigCsvForChip(uint8_t chip) {
  uint8_t r0 = readRegAB(chip, 0);
  uint8_t r1 = readRegAB(chip, 1);
  uint8_t r2 = readRegAB(chip, 2);
  uint8_t r3 = readRegAB(chip, 3);
  uint8_t r4 = readRegAB(chip, 4);
  uint8_t r5 = readRegAB(chip, 5);
  uint8_t r6 = readRegAB(chip, 6);
  uint8_t r8 = readRegAB(chip, 8);
  Serial.printf("%u, %u, %u, %u, %u, %u, %u, %u\n",
                r0, r1, r2, r3, r4, r5, r6, r8);
}

/* =================== Appliquer la config =================== */
void applyABeastConfigToChip(uint8_t chip, const ABeastConfig& cfg, bool verify=false) {
  writeRegAB(chip, 0, cfg.vpre_bias);
  writeRegAB(chip, 1, cfg.sh_vcm);
  writeRegAB(chip, 2, cfg.sh_timebias);
  writeRegAB(chip, 3, cfg.vth_baseline);
  writeRegAB(chip, 4, cfg.comp_vth_0);
  writeRegAB(chip, 5, cfg.comp_vth_1);
  writeRegAB(chip, 6, cfg.comp_vth_2);
  writeRegAB(chip, 8, cfg.reg_8);

  if (verify) {
    Serial.printf("[CFG] Chip %u: r0=%u r1=%u r2=%u r3=%u r4=%u r5=%u r6=%u r8=%u\n",
      chip,
      readRegAB(chip,0), readRegAB(chip,1), readRegAB(chip,2), readRegAB(chip,3),
      readRegAB(chip,4), readRegAB(chip,5), readRegAB(chip,6), readRegAB(chip,8)
    );
  }
}

void applyDefaultConfigABeasts(bool verify=false){
  for (uint8_t chip=0; chip<NUM_ABEAST; ++chip){
    applyABeastConfigToChip(chip, DEFAULT_CFG[chip], verify);
  }
}

/* =================== Compteurs =================== */

// --- petite fonction pour lire un octet de registre "addr" sur un chip ---
uint8_t readReg_raw(uint8_t chip, uint8_t addr) {
  SPI.beginTransaction(abeastSPISettings);
  int cs = chipToCS(chip);
  digitalWrite(cs, LOW);
  delayMicroseconds(6);
  uint16_t r = SPI.transfer16(((uint16_t)addr) << 8);
  delayMicroseconds(4);
  digitalWrite(cs, HIGH);
  SPI.endTransaction();
  return (uint8_t)(r & 0xFF);
}

// --- lecture compteur 24 bits robuste ---
uint32_t readSingleCounter(int abeast, int counter) {
  const uint8_t base   = 9;
  const uint8_t stride = 3;

  if (abeast < 0 || abeast >= NUM_ABEAST || counter < 0 || counter >= NUM_COUNTERS_PER_ABEAST) {
    return 0;
  }

  uint8_t aL = base + stride * counter + 0;
  uint8_t aM = base + stride * counter + 1;
  uint8_t aH = base + stride * counter + 2;

  for (int tries = 0; tries < 8; ++tries) {
    uint8_t h1 = readReg_raw(abeast, aH);
    uint8_t m  = readReg_raw(abeast, aM);
    uint8_t l  = readReg_raw(abeast, aL);
    uint8_t h2 = readReg_raw(abeast, aH);

    if (h1 == h2) {
      return ((uint32_t)h1 << 16) | ((uint32_t)m << 8) | (uint32_t)l;
    }

    delayMicroseconds(50);
  }

  // fallback best-effort
  uint8_t h = readReg_raw(abeast, aH);
  uint8_t m = readReg_raw(abeast, aM);
  uint8_t l = readReg_raw(abeast, aL);
  return ((uint32_t)h << 16) | ((uint32_t)m << 8) | (uint32_t)l;
}

void printAllCounters(){
  Serial.println("COUNTERS:");
  for (int chip=0; chip<NUM_ABEAST; ++chip){
    uint32_t c0 = readSingleCounter(chip, 0);
    uint32_t c1 = readSingleCounter(chip, 1);
    uint32_t c2 = readSingleCounter(chip, 2);
    Serial.printf("  chip%d: c0=%lu c1=%lu c2=%lu\n", chip, (unsigned long)c0, (unsigned long)c1, (unsigned long)c2);
  }
}

/* =================== Reset compteurs =================== */
void resetCountersAll(){
  for (int chip=0; chip<NUM_ABEAST; ++chip){
    uint8_t r8 = readRegAB(chip, 8);
    // pulse bit rst_c
    writeRegAB(chip, 8, r8 | (1u<<REG8_RST_C_BIT));
  }
  delay(2);
  for (int chip=0; chip<NUM_ABEAST; ++chip){
    uint8_t r8 = readRegAB(chip, 8);
    writeRegAB(chip, 8, r8 & ~(1u<<REG8_RST_C_BIT));
  }
}

/* =================== Utilitaires =================== */
long toLong(const String& s, int base=10){
  char *end=nullptr;
  long v = strtol(s.c_str(), &end, base);
  return v;
}

/* =================== Commandes série ===================

HELP
  -> liste les commandes

CFG.APPLY
  -> applique la config par défaut aux 3 ABeasts (sans vérif)

CFG.APPLYV
  -> applique la config par défaut avec vérification (dump des r0..r6,r8)

CFG.READ <chip>
  -> lit r0,r1,r2,r3,r4,r5,r6,r8 pour <chip> in {0,1,2}

REG.R <chip> <addr>
  -> lit un registre, affiche sa valeur décimale

REG.W <chip> <addr> <val>
  -> écrit un registre

CNT?
  -> lit et affiche les 3 compteurs de chaque ABeast

ZERO
  -> remet à zéro les compteurs (pulse rst_c sur reg8)

MUX <0|1|2|3>
  -> sélectionne le canal du MUX (0 = analog OFF, 1–3 = analog ON)
*/
void handleLine(String line){
  line.trim();
  if (line.length()==0) return;

  String cmd; int sp=line.indexOf(' ');
  if (sp<0) cmd = line; else cmd = line.substring(0, sp);
  String rest = (sp<0) ? "" : line.substring(sp+1);

  if (cmd=="HELP"){
    Serial.println("Commands:");
    Serial.println("  HELP");
    Serial.println("  BIAS");
    Serial.println("  CFG.APPLY");
    Serial.println("  CFG.APPLYV");
    Serial.println("  CFG.READ <chip>");
    Serial.println("  REG.R <chip> <addr>");
    Serial.println("  REG.W <chip> <addr> <val>");
    Serial.println("  CNT?");
    Serial.println("  ZERO");
    Serial.println("  CNTCSV");
    Serial.println("  MUX <0|1|2|3>         (canal brut, 0=analog OFF)");
    Serial.println("  MUX Abeast0/1/2      (A1A0 = 01 / 10 / 11)");
    return;
  }
  if (cmd=="BIAS"){
    for (uint8_t chip=0; chip<NUM_ABEAST; ++chip){
      printConfigCsvForChip(chip);
    }
    return;
  }
  if (cmd=="CFG.APPLY"){
    applyDefaultConfigABeasts(false);
    Serial.println("OK CFG.APPLY");
    return;
  }
  if (cmd=="CFG.APPLYV"){
    applyDefaultConfigABeasts(true);
    Serial.println("OK CFG.APPLYV");
    return;
  }
  if (cmd=="CNTCSV"){
    for (int chip=0; chip<NUM_ABEAST; ++chip){
      uint32_t c0 = readSingleCounter(chip,0);
      uint32_t c1 = readSingleCounter(chip,1);
      uint32_t c2 = readSingleCounter(chip,2);
      Serial.printf("%d,%lu,%lu,%lu\n", chip, (unsigned long)c0, (unsigned long)c1, (unsigned long)c2);
    }
    return;
  }
  if (cmd=="CFG.READ"){
    int chip = toLong(rest);
    if (chip<0 || chip>=NUM_ABEAST){ Serial.println("ERR chip"); return; }
    uint8_t r[9];
    r[0]=readRegAB(chip,0); r[1]=readRegAB(chip,1); r[2]=readRegAB(chip,2);
    r[3]=readRegAB(chip,3); r[4]=readRegAB(chip,4); r[5]=readRegAB(chip,5);
    r[6]=readRegAB(chip,6); r[8]=readRegAB(chip,8);
    Serial.printf("CFG chip%d: r0=%u r1=%u r2=%u r3=%u r4=%u r5=%u r6=%u r8=%u\n",
                  chip, r[0],r[1],r[2],r[3],r[4],r[5],r[6],r[8]);
    return;
  }
  if (cmd=="ID?"){
    Serial.printf("ESP_abeast_ID=%d\n", ESP_Abeast_ID);
    return;
  }

  if (cmd=="REG.R"){
    int sp2 = rest.indexOf(' ');
    if (sp2<0){ Serial.println("ERR args"); return; }
    int chip = toLong(rest.substring(0, sp2));
    int addr = toLong(rest.substring(sp2+1));
    if (chip<0 || chip>=NUM_ABEAST || addr<0 || addr>255){ Serial.println("ERR args"); return; }
    uint8_t v = readRegAB(chip, (uint8_t)addr);
    Serial.printf("REG.R chip%d addr%d => %u\n", chip, addr, v);
    return;
  }
  if (cmd=="REG.W"){
    int sp2 = rest.indexOf(' ');
    int sp3 = (sp2<0) ? -1 : rest.indexOf(' ', sp2+1);
    if (sp2<0 || sp3<0){ Serial.println("ERR args"); return; }
    int chip = toLong(rest.substring(0, sp2));
    int addr = toLong(rest.substring(sp2+1, sp3));
    int val  = toLong(rest.substring(sp3+1));
    if (chip<0 || chip>=NUM_ABEAST || addr<0 || addr>255 || val<0 || val>255){ Serial.println("ERR args"); return; }
    writeRegAB(chip, (uint8_t)addr, (uint8_t)val);
    Serial.println("OK REG.W");
    return;
  }
  if (cmd=="CNT?"){
    printAllCounters();
    return;
  }
  if (cmd=="ZERO"){
    resetCountersAll();
    Serial.println("OK ZERO");
    return;
  }
  if (cmd=="MUX"){
    rest.trim();
    // Cas "MUX Abeast0", "MUX Abeast1", "MUX Abeast2"
    if (rest.startsWith("Abeast") || rest.startsWith("ABeast") || rest.startsWith("ABEAST")) {
      // on récupère le numéro après "Abeast"
      int idx = rest.substring(6).toInt();   // "Abeast0" -> "0"
      if (idx < 0 || idx > 2) {
        Serial.println("ERR MUX Abeast index (0..2)");
        return;
      }
      selectAbeast((uint8_t)idx);
      Serial.printf("OK MUX Abeast%d\n", idx);
      return;
    }

    // Cas historique : "MUX 0/1/2/3"
    int ch = toLong(rest);
    if (ch<0 || ch>3){
      Serial.println("ERR MUX");
      return;
    }
    setMuxChannel((uint8_t)ch);
    Serial.printf("OK MUX %d\n", ch);
    return;
  }


  Serial.println("ERR unknown");
}

/* =================== Setup / Loop =================== */
void setup(){
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, HIGH);

  Serial.begin(BAUD_RATE);
  while (!Serial) { delay(10); }

  // SPI + broches
  SPI.begin();
  pinMode(CS_PIN_0, OUTPUT);
  pinMode(CS_PIN_1, OUTPUT);
  pinMode(CS_PIN_2, OUTPUT);
  pinMode(CS_PIN_FLASH, OUTPUT);
  pinMode(MUX_A0, OUTPUT);
  pinMode(MUX_A1, OUTPUT);
  digitalWrite(CS_PIN_0, HIGH);
  digitalWrite(CS_PIN_1, HIGH);
  digitalWrite(CS_PIN_2, HIGH);
  digitalWrite(CS_PIN_FLASH, HIGH);

  // *** NEW: on démarre directement avec le MUX sur 1 => ENABLE = ON ***
  //  -> VDDA + AOP ON, SH1/SH2/SH3 prêts
  setMuxChannel(1);

  // Config SPI “safe”
  SPI.setClockDivider(SPI_CLOCK_DIV64);
  SPI.setDataMode(SPI_MODE1);
  SPI.setBitOrder(MSBFIRST);

  // Réveil bus + application config par défaut
  (void) read_write_reg(0, 2, 0x00, /*read=*/true);
  (void) read_write_reg(1, 2, 0x00, /*read=*/true);
  (void) read_write_reg(2, 2, 0x00, /*read=*/true);

  Serial.println("=== AlphaBeast Serial Controller (no Wi-Fi) ===");
  Serial.printf("ESP_abeast_ID=%d \n", ESP_Abeast_ID);
  Serial.println("Applying default config...");
  applyDefaultConfigABeasts(/*verify=*/true);
  Serial.println("Type HELP for commands.");
}

void loop(){
  if (Serial.available()){
    String line = Serial.readStringUntil('\n');
    handleLine(line);
  }
}

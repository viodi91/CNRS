#include <SPI.h>
#include <ESP8266WiFi.h>

// Paramètres WiFi - CONFIGURATION CORRIGÉE
const char* ssid = "ESP";
const char* password = "11111111";
unsigned long lastHeartbeatTime = 0;
const unsigned long heartbeatInterval = 30000; // Heartbeat toutes les 30s
// Adresse IP et port du serveur - CORRIGÉE POUR VOTRE CONFIGURATION
// ===== IP fixe ESP (dans le subnet du hotspot Raspberry) =====
IPAddress local_IP(192, 168, 50, 30);
IPAddress gateway(192, 168, 50, 1);
IPAddress dns1(192, 168, 50, 1);
IPAddress subnet(255, 255, 255, 0);
const int tcpPort = 4210;          // <-- DOIT être global
IPAddress serverIP(192, 168, 50, 1); // <-- hotspot Pi

// String ESP_UNIQUE_ID = "ESP_ABEAST_03";      
// String ESP_DESCRIPTION = "AlphaBeast Controller #3"; 
String ESP_UNIQUE_ID = "ESP_ABEAST_01";      
String ESP_DESCRIPTION = "AlphaBeast Controller #1"; 
unsigned long lastTcpOk = 0;
// États et modes
bool wifiEnabled = true;
bool serialEnabled = true;
bool clientConnected = false;
unsigned long lastPingTime = 0;
const unsigned long pingInterval   = 5000;     // 5s
String tcpLineBuf;
// Client WiFi
WiFiClient client;

// Broches SPI
const int CS_PIN_0 = 5;
const int CS_PIN_1 = 4;
const int CS_PIN_2 = 0;
const int CS_PIN_FLASH = 2;  // GPIO2 pour la flash
const int MUX_A0 = 16;
const int MUX_A1 = 15;

// Configuration SPI Flash - OPTIMISÉE pour stabilité
SPISettings flashSPISettings(400000, MSBFIRST, SPI_MODE0);  

// Commandes SPI de la flash MT25QL256ABA1EW7
#define CMD_4READ            0x13   // 4-byte READ
#define CMD_4PP              0x12   // 4-byte PAGE PROGRAM
#define CMD_4SECTOR_ERASE    0x21   // 4-byte 4KB sector erase

#define CMD_READ_ID           0x9F
// #define CMD_READ_DATA         0x03
#define CMD_WRITE_ENABLE      0x06
// #define CMD_WRITE_DISABLE     0x04
#define CMD_READ_STATUS       0x05
// #define CMD_PAGE_PROGRAM      0x02
// #define CMD_SECTOR_ERASE      0x20
// Configuration du logging
#define NUM_ABEAST            3
#define NUM_COUNTERS_PER_ABEAST 3
#define TOTAL_COUNTERS        (NUM_ABEAST * NUM_COUNTERS_PER_ABEAST)
// Taille des pages et secteurs de la flash
#define PAGE_SIZE             256
#define SECTOR_SIZE           4096
// ======== CONFIG ABeast PAR DÉFAUT (compilée en dur) ========
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

// Valeurs config pour espabeast 1
const ABeastConfig DEFAULT_CFG[NUM_ABEAST] = {
  // ABeast_1
  {124, 194, 115, 96, 232, 200, 178, 13},
  // ABeast_2
  {124, 194, 115, 88, 206, 173, 149, 13},
  // ABeast_3
  {124, 194, 115, 90, 214, 178, 163, 13}
};
// Valeurs config pour espabeast 2
// const ABeastConfig DEFAULT_CFG[NUM_ABEAST] = {
//   // ABeast_1
//   {124, 194, 115, 98, 235, 199, 174, 13},
//   // ABeast_2
//   {124, 194, 115, 98, 235, 204, 190, 13},
//   // ABeast_3 BL TH1 : 157  TH 2 : 156
//   {124, 194, 115, 120, 235, 112, 88, 13}
// };
//Valeurs config pour espabeast 3
// const ABeastConfig DEFAULT_CFG[NUM_ABEAST] = {
//   // ABeast_1
//   {124, 194, 115, 96, 230, 205, 200, 13},
//   // ABeast_2
//   {124, 194, 115, 88, 235, 200, 189, 13},
//   // ABeast_3
//   {124, 194, 115, 101, 235, 205, 190, 13}
// };
// Helper écriture d’un registre (utilise read_write_reg existant)
static inline void writeRegAB(uint8_t chip, uint8_t addr, uint8_t val) {
  // read_write_reg(chip, address, value, readFlag)
  read_write_reg((char)chip, (char)addr, (char)val, /*read=*/false);
  delay(2);
}

// (Optionnel) lecture pour vérif
static inline uint8_t readRegAB(uint8_t chip, uint8_t addr) {
  return (uint8_t)read_write_reg((char)chip, (char)addr, (char)0x00, /*read=*/true);
}

// Applique une config à un ABeast donné (chip = 0,1,2)
void applyABeastConfigToChip(uint8_t chip, const ABeastConfig& cfg, bool verify=false) {
  writeRegAB(chip, 0, cfg.vpre_bias);
  writeRegAB(chip, 1, cfg.sh_vcm);
  writeRegAB(chip, 2, cfg.sh_timebias);
  writeRegAB(chip, 3, cfg.vth_baseline);
  writeRegAB(chip, 4, cfg.comp_vth_0);
  writeRegAB(chip, 5, cfg.comp_vth_1);
  writeRegAB(chip, 6, cfg.comp_vth_2);
  writeRegAB(chip, 8, cfg.reg_8);

  if (serialEnabled && verify) {
    Serial.printf("[CFG] Chip %u: r0=%u r1=%u r2=%u r3=%u r4=%u r5=%u r6=%u r8=%u\n",
      chip,
      readRegAB(chip,0), readRegAB(chip,1), readRegAB(chip,2), readRegAB(chip,3),
      readRegAB(chip,4), readRegAB(chip,5), readRegAB(chip,6), readRegAB(chip,8)
    );
  }
}
// void sendResponseFast(const char* message, bool doFlush = false) {
//   // Serial si activé
//   if (serialEnabled) {
//     Serial.print(message);
//   }

//   // TCP si connecté
//   if (wifiEnabled && clientConnected) {
//     client.print(message);
//     if (doFlush) client.flush();
//   }
// }
bool sendResponseFast(const char* s, bool flushNow=true) {
  if (!(wifiEnabled && clientConnected)) return false;

  static uint8_t fail = 0;

  // flush-only
  if (s == nullptr || s[0] == '\0') {
    if (flushNow) client.flush();
    lastTcpOk = millis();
    fail = 0;
    return true;
  }

  // Si déjà mort
  if (!client.connected()) {
    client.stop();
    clientConnected = false;
    fail = 0;
    return false;
  }

  size_t n = client.print(s);
  if (flushNow) client.flush();

  // ✅ Critère simple : n==0 répété => on coupe
  if (n == 0) fail++;
  else { fail = 0; lastTcpOk = millis(); }

  if (fail >= 8) {            // ✅ moins agressif que 3
    client.stop();
    clientConnected = false;
    fail = 0;
    return false;
  }

  return true;
}





// Applique la config aux 3 matrices
void applyDefaultConfigABeasts(bool verify=false) {
  for (uint8_t chip = 0; chip < NUM_ABEAST; ++chip) {
    applyABeastConfigToChip(chip, DEFAULT_CFG[chip], verify);
  }
}


// Structure des données de log (40 bytes par entrée)
struct LogEntry {
  uint32_t timestamp;     // 4 bytes - temps en secondes depuis le boot
  uint32_t counters[9];   // 36 bytes - 9 compteurs de 4 bytes chacun
} __attribute__((packed)); // Total: 40 bytes

// Variables de logging FINALES
unsigned long lastLogTime = 0;
unsigned long logInterval = 5000; // 5 secondes par défaut
uint32_t currentLogAddress = 0;
uint32_t maxLogEntries = 0;
uint32_t currentLogEntry = 0;
bool loggingEnabled = true;
bool flashInitialized = false;

// STRATÉGIE SÉQUENTIELLE SIMPLE
uint32_t nextWriteAddress = 0;  // Adresse séquentielle simple

// Variables de diagnostic
uint32_t writeRetryCount = 0;
uint32_t writeFailureCount = 0;
uint32_t totalWriteAttempts = 0;
uint32_t sectorsErased = 0;

// Adresses de la flash
#define FLASH_LOG_START_ADDRESS  0x010000  // Commence à 64KB
#define FLASH_METADATA_ADDRESS   0x000000  // Métadonnées au début
#define FLASH_LOG_SIZE           (32 * 1024 * 1024 - FLASH_LOG_START_ADDRESS) // Reste de la flash

// Paramètres de communication
const long BAUD_RATE = 115200;
const int BUFFER_SIZE = 1;

// Variables pour la reconnexion - AMÉLIORÉES
unsigned long lastReconnectAttempt = 0;
const unsigned long reconnectInterval = 10000;  // Augmenté à 10s
unsigned long lastWifiCheck = 0;
const unsigned long wifiCheckInterval = 30000;  // Vérification WiFi toutes les 30s

// Variables pour le clignotement LED
unsigned long lastBlinkTime = 0;
const int LED_PIN = -1; // LED désactivée (GPIO2 est CS_FLASH)


// Command types
const byte CMD_READ = 0x00;
const byte CMD_WRITE = 0x01;
char buffer[200];
uint8_t RX_Buffer[2] = {0};

// ========== FONCTIONS FLASH DE BASE ==========

void flashSelect() {
  digitalWrite(CS_PIN_FLASH, LOW);
  delayMicroseconds(10);
}

void flashDeselect() {
  delayMicroseconds(10);
  digitalWrite(CS_PIN_FLASH, HIGH);
}

uint8_t flashSpiTransfer(uint8_t data) {
  return SPI.transfer(data);
}
void setMuxChannel(uint8_t channel) {
  digitalWrite(MUX_A0, LOW);
  digitalWrite(MUX_A1, LOW);
  
  switch (channel) {
    case 0:
      // Canal 0 : A1=0, A0=0 (déjà fait)
      break;
    case 1:
      digitalWrite(MUX_A0, HIGH);  // A1=0, A0=1
      break;
    case 2:
      digitalWrite(MUX_A1, HIGH);  // A1=1, A0=0
      break;
    case 3:
      digitalWrite(MUX_A0, HIGH);  // A1=1, A0=1
      digitalWrite(MUX_A1, HIGH);
      break;
    default:
      // Canal 0 par défaut
      break;
  }
  
  if (serialEnabled) {
    Serial.printf("MUX canal %d sélectionné\n", channel);
  }
}
void writeEnable() {
  SPI.beginTransaction(flashSPISettings);
  flashSelect();
  flashSpiTransfer(CMD_WRITE_ENABLE);
  flashDeselect();
  SPI.endTransaction();
  delayMicroseconds(20);
}

uint8_t readFlashStatus() {
  SPI.beginTransaction(flashSPISettings);
  flashSelect();
  flashSpiTransfer(CMD_READ_STATUS);
  uint8_t status = flashSpiTransfer(0x00);
  flashDeselect();
  SPI.endTransaction();
  return status;
}

// void waitForFlashReady() {
//   unsigned long startTime = millis();
//   while (readFlashStatus() & 0x01) {
//     delay(1);
//     if (millis() - startTime > 5000) {
//       if (serialEnabled) {
//         Serial.println("WARNING: Flash operation timeout");
//       }
//       break;
//     }
//   }
// }
void waitForFlashReady() {
  unsigned long startTime = millis();
  while (readFlashStatus() & 0x01) {
    delay(1);
    yield();   // ✅ ici c’est safe
    if (millis() - startTime > 5000) {
      if (serialEnabled) Serial.println("WARNING: Flash operation timeout");
      break;
    }
  }
}



bool testFlashID() {
  SPI.beginTransaction(flashSPISettings);
  flashSelect();
  
  flashSpiTransfer(CMD_READ_ID);
  uint8_t id1 = flashSpiTransfer(0x00);
  uint8_t id2 = flashSpiTransfer(0x00);
  uint8_t id3 = flashSpiTransfer(0x00);
  
  flashDeselect();
  SPI.endTransaction();
  
  if (serialEnabled) {
    Serial.printf("Flash ID: 0x%02X 0x%02X 0x%02X\n", id1, id2, id3);
  }
  
  return (id1 == 0x20 && id2 == 0xBA && id3 == 0x19);
}
void sendCountersCsvOnce() {
  char line[256];

  for (int chip = 0; chip < NUM_ABEAST; ++chip) {
    uint32_t c0 = readSingleCounter(chip, 0);
    uint32_t c1 = readSingleCounter(chip, 1);
    uint32_t c2 = readSingleCounter(chip, 2);

    // même format que ta version série:
    // chip,c0,c1,c2
    snprintf(line, sizeof(line), "%d,%lu,%lu,%lu\n",
             chip, (unsigned long)c0, (unsigned long)c1, (unsigned long)c2);

    sendResponseFast(line, false);  // envoi TCP + éventuellement Serial selon ton flag
  }
  sendResponseFast("OK CNTCSV\n", true);
}

// void sectorErase(uint32_t address) {
//   uint32_t sectorAddr = address & ~(SECTOR_SIZE - 1);

//   writeEnable();
//   delay(2);

//   SPI.beginTransaction(flashSPISettings);
//   flashSelect();
//   flashSpiTransfer(CMD_SECTOR_ERASE);
//   flashSpiTransfer((sectorAddr >> 16) & 0xFF);
//   flashSpiTransfer((sectorAddr >> 8) & 0xFF);
//   flashSpiTransfer(sectorAddr & 0xFF);
//   flashDeselect();
//   SPI.endTransaction();

//   waitForFlashReady();   // yield inside
//   delay(10);
// }
void sectorErase(uint32_t address) {
  uint32_t sectorAddr = address & ~(SECTOR_SIZE - 1);

  writeEnable();
  SPI.beginTransaction(flashSPISettings);
  flashSelect();
  SPI.transfer(CMD_4SECTOR_ERASE);
  SPI.transfer((sectorAddr >> 24) & 0xFF);
  SPI.transfer((sectorAddr >> 16) & 0xFF);
  SPI.transfer((sectorAddr >> 8) & 0xFF);
  SPI.transfer(sectorAddr & 0xFF);
  flashDeselect();
  SPI.endTransaction();

  waitForFlashReady();
}


static inline uint32_t advanceAddr(uint32_t addr) {
  // addr pointe sur le début d’une entry
  // prochaine entry logique = addr + sizeof(LogEntry), mais en respectant l’alignement page
  uint32_t next = addr + sizeof(LogEntry);

  // si la prochaine entry traverserait une page, on aligne
  uint32_t endAddr = next + sizeof(LogEntry) - 1;
  uint32_t startPage = next / PAGE_SIZE;
  uint32_t endPage   = endAddr / PAGE_SIZE;
  if (startPage != endPage) next = (startPage + 1) * PAGE_SIZE;

  return next;
}

// FONCTION DE VÉRIFICATION DE SECTEUR
bool isSectorEmpty(uint32_t sectorAddress) {
  uint32_t sectorStart = sectorAddress & ~(SECTOR_SIZE - 1);
  
  // Vérifier les 64 premiers bytes du secteur
  uint8_t testData[64];
  readFlashData(sectorStart, testData, 64);
  
  for (int i = 0; i < 64; i++) {
    if (testData[i] != 0xFF) {
      return false; // Secteur contient des données
    }
  }
  return true; // Secteur vide
}

// FONCTION D'ÉCRITURE SÉQUENTIELLE ULTRA-SIMPLE
bool writeFlashSequential(uint32_t address, uint8_t* data, uint16_t length) {
  if (length > PAGE_SIZE) {
    length = PAGE_SIZE;
  }
  
  // VÉRIFICATION CRITIQUE : Pas de traversée de page
  uint32_t endAddress = address + length - 1;
  uint32_t startPage = address / PAGE_SIZE;
  uint32_t endPage = endAddress / PAGE_SIZE;
  
  if (startPage != endPage) {
    if (serialEnabled) {
      Serial.printf("❌ Écriture traverse page 0x%06X-0x%06X\n", address, endAddress);
    }
    return false;
  }
  
  // Vérifier si le secteur doit être effacé
  uint32_t sectorStart = address & ~(SECTOR_SIZE - 1);
  uint32_t sectorOffset = address - sectorStart;
  
  // Effacer le secteur SEULEMENT s'il n'est pas vide ET qu'on écrit au début
  if (sectorOffset == 0 || !isSectorEmpty(sectorStart)) {
    if (sectorOffset == 0) {
      // Début de secteur : effacer proprement
      if (serialEnabled) {
        Serial.printf("🧹 Effacement secteur neuf 0x%06X\n", sectorStart);
      }
      sectorErase(sectorStart);
    } else {
      // Milieu de secteur : vérifier s'il faut effacer
      uint8_t testData[40];
      readFlashData(address, testData, 40);
      
      bool needErase = false;
      for (int i = 0; i < 40; i++) {
        if (testData[i] != 0xFF) {
          needErase = true;
          break;
        }
      }
      
      if (needErase) {
        if (serialEnabled) {
          Serial.printf("🗑️ Effacement secteur nécessaire 0x%06X\n", sectorStart);
        }
        sectorErase(sectorStart);
      }
    }
  }
  
  totalWriteAttempts++;
  
  // ÉCRITURE ROBUSTE avec vérification
  // ÉCRITURE ROBUSTE avec vérification
for (int attempt = 0; attempt < 3; attempt++) {

  writeEnable();
  delay(2);

  SPI.beginTransaction(flashSPISettings);
  flashSelect();
  // flashSpiTransfer(CMD_PAGE_PROGRAM);
  // flashSpiTransfer((address >> 16) & 0xFF);
  // flashSpiTransfer((address >> 8) & 0xFF);
  // flashSpiTransfer(address & 0xFF);
  flashSpiTransfer(CMD_4PP);
  flashSpiTransfer((address >> 24) & 0xFF);
  flashSpiTransfer((address >> 16) & 0xFF);
  flashSpiTransfer((address >> 8) & 0xFF);
  flashSpiTransfer(address & 0xFF);

  // Écriture lente et stable + yield SAFE (interruptions ON)
  for (uint16_t i = 0; i < length; i++) {
    flashSpiTransfer(data[i]);
    delayMicroseconds(30);

    if ((i % 16) == 15) yield();   // ✅ safe ici
    if ((i % 8)  == 7)  delayMicroseconds(100);
  }

  flashDeselect();
  SPI.endTransaction();

  waitForFlashReady();  // on met yield dedans aussi (voir plus bas)
  delay(2);

  // VLA interdit -> buffer fixe
  uint8_t readback[PAGE_SIZE];
  readFlashData(address, readback, length);

  bool writeOK = true;
  for (uint16_t i = 0; i < length; i++) {
    if (data[i] != readback[i]) { writeOK = false; break; }
  }

  if (writeOK) return true;

  delay(50 + attempt * 50);
}

return false;
}

void readFlashData(uint32_t address, uint8_t* buffer, uint16_t length) {
  SPI.beginTransaction(flashSPISettings);
  flashSelect();
  SPI.transfer(CMD_4READ);
  SPI.transfer((address >> 24) & 0xFF);
  SPI.transfer((address >> 16) & 0xFF);
  SPI.transfer((address >> 8) & 0xFF);
  SPI.transfer(address & 0xFF);

  for (uint16_t i = 0; i < length; i++) buffer[i] = SPI.transfer(0x00);

  flashDeselect();
  SPI.endTransaction();
}

// void readFlashData(uint32_t address, uint8_t* buffer, uint16_t length) {
//   SPI.beginTransaction(flashSPISettings);
//   flashSelect();
//   flashSpiTransfer(CMD_READ_DATA);
//   flashSpiTransfer((address >> 16) & 0xFF);
//   flashSpiTransfer((address >> 8) & 0xFF);
//   flashSpiTransfer(address & 0xFF);

//   for (uint16_t i = 0; i < length; i++) {
//     buffer[i] = flashSpiTransfer(0x00);
//     if ((i & 31) == 31) yield();  // <<< toutes les 32 bytes
//   }

//   flashDeselect();
//   SPI.endTransaction();
// }


// ========== FONCTIONS DE LOGGING ULTRA-SIMPLIFIÉES ==========

// CALCUL D'ADRESSE SÉQUENTIEL SIMPLE avec alignement page
uint32_t getNextAlignedAddress() {
  uint32_t address = nextWriteAddress;
  
  // Vérifier si l'écriture traverserait une frontière de page
  uint32_t endAddress = address + sizeof(LogEntry) - 1;
  uint32_t startPage = address / PAGE_SIZE;
  uint32_t endPage = endAddress / PAGE_SIZE;
  
  if (startPage != endPage) {
    // Aligner sur la page suivante
    address = (startPage + 1) * PAGE_SIZE;
    if (serialEnabled) {
      Serial.printf("📦 Alignement page 0x%06X -> 0x%06X\n", nextWriteAddress, address);
    }
  }
  
  return address;
}

bool initializeFlash() {
  if (!testFlashID()) {
    if (serialEnabled) {
      Serial.println("Erreur: Flash non détectée");
    }
    return false;
  }
  
  maxLogEntries = FLASH_LOG_SIZE / sizeof(LogEntry);
  
  // Lire les métadonnées simplifiées
  uint32_t metadata[3];
  readFlashData(FLASH_METADATA_ADDRESS, (uint8_t*)metadata, 12);
  
  currentLogEntry = metadata[0];
  uint32_t magic = metadata[1];
  nextWriteAddress = metadata[2];
  
  // Vérifier la validité
  if (magic != 0xDEADBEEF || currentLogEntry > maxLogEntries || nextWriteAddress < FLASH_LOG_START_ADDRESS) {
    if (serialEnabled) {
      Serial.println("Initialisation flash - reset métadonnées");
    }
    currentLogEntry = 0;
    nextWriteAddress = FLASH_LOG_START_ADDRESS;
    sectorErase(FLASH_METADATA_ADDRESS);
    updateMetadata();  // scelle {0, 0xDEADBEEF, 0x010000} tout de suit
  }
  
  currentLogAddress = nextWriteAddress;
  flashInitialized = true;
  
  if (serialEnabled) {
    Serial.printf("Flash initialisée - Entrées: %d\n", currentLogEntry);
    Serial.printf("Prochaine adresse: 0x%06X\n", nextWriteAddress);
    Serial.printf("Taille LogEntry: %d bytes\n", sizeof(LogEntry));
  }
  
  return true;
}

void updateMetadata() {
  uint32_t metadata[3];
  metadata[0] = currentLogEntry;
  metadata[1] = 0xDEADBEEF; // Magic number
  metadata[2] = nextWriteAddress;
  
  // Effacer métadonnées périodiquement
  if (currentLogEntry % 500 == 0) {
    sectorErase(FLASH_METADATA_ADDRESS);
  }
  
  writeFlashSequential(FLASH_METADATA_ADDRESS, (uint8_t*)metadata, 12);
}

static inline uint8_t readCounterByte(int abeast, uint16_t addr) {
  SPISettings s(2000000, MSBFIRST, SPI_MODE1);

  int cs_pin = (abeast == 0) ? CS_PIN_0 : (abeast == 1) ? CS_PIN_1 : CS_PIN_2;

  uint16_t var1 = (addr << 8); // lecture: value=0
  SPI.beginTransaction(s);
  digitalWrite(cs_pin, LOW);
  delayMicroseconds(10);
  uint16_t res = SPI.transfer16(var1);
  delayMicroseconds(10);
  digitalWrite(cs_pin, HIGH);
  SPI.endTransaction();

  return (uint8_t)(res & 0xFF);
}

uint32_t readSingleCounter(int abeast, int counter) {
  const uint16_t counterpos = 9; // nreg + 1
  const uint16_t ncounter   = 3;

  if (abeast < 0 || abeast >= NUM_ABEAST || counter < 0 || counter >= NUM_COUNTERS_PER_ABEAST) {
    return 0;
  }

  uint16_t addr_low  = counterpos + ncounter * counter;
  uint16_t addr_mid  = addr_low + 1;
  uint16_t addr_high = addr_low + 2;

  for (int attempt = 0; attempt < 8; ++attempt) {
    uint8_t h1 = readCounterByte(abeast, addr_high);
    uint8_t m  = readCounterByte(abeast, addr_mid);
    uint8_t l  = readCounterByte(abeast, addr_low);
    uint8_t h2 = readCounterByte(abeast, addr_high);

    if (h1 == h2) {
      return ((uint32_t)h1 << 16) | ((uint32_t)m << 8) | (uint32_t)l;
    }

    // Ça a bougé pendant lecture -> retente
    delayMicroseconds(50);
    yield(); // important sur ESP8266 (WiFi watchdog)
  }

  // fallback best-effort
  uint8_t h = readCounterByte(abeast, addr_high);
  uint8_t m = readCounterByte(abeast, addr_mid);
  uint8_t l = readCounterByte(abeast, addr_low);
  return ((uint32_t)h << 16) | ((uint32_t)m << 8) | (uint32_t)l;
}


// FONCTION DE LOGGING ULTRA-SIMPLE : séquentielle pure
void logCountersSequential() {
  if (!flashInitialized || !loggingEnabled) {
    return;
  }
  
  LogEntry entry;
  entry.timestamp = millis() / 1000;
  
  // Lire tous les compteurs
  for (int abeast = 0; abeast < NUM_ABEAST; abeast++) {
    for (int counter = 0; counter < NUM_COUNTERS_PER_ABEAST; counter++) {
      int index = abeast * NUM_COUNTERS_PER_ABEAST + counter;
      entry.counters[index] = readSingleCounter(abeast, counter);
    }
  }
  
  // Obtenir l'adresse alignée suivante
  uint32_t writeAddress = getNextAlignedAddress();
  
  // Vérifier qu'on ne dépasse pas la zone
  if (writeAddress + sizeof(LogEntry) >= (FLASH_LOG_START_ADDRESS + FLASH_LOG_SIZE)) {
    if (serialEnabled) {
      Serial.println("📦 Zone pleine, retour au début");
    }
    nextWriteAddress = FLASH_LOG_START_ADDRESS;
    currentLogEntry = 0;
    writeAddress = FLASH_LOG_START_ADDRESS;
  }
  
  if (serialEnabled && (currentLogEntry % 10 == 0)) {
    Serial.printf("📝 Log %d -> 0x%06X\n", currentLogEntry, writeAddress);
  }
  
  // ÉCRITURE SÉQUENTIELLE
  if (writeFlashSequential(writeAddress, (uint8_t*)&entry, sizeof(LogEntry))) {
    // Succès : avancer les pointeurs
    currentLogEntry++;
    nextWriteAddress = advanceAddr(writeAddress);

    currentLogAddress = nextWriteAddress;
    
    
    updateMetadata();
   
    
    if (serialEnabled && currentLogEntry % 50 == 0) {
      Serial.printf("✅ %d entrées OK\n", currentLogEntry);
    }
  } else {
    if (serialEnabled) {
      Serial.printf("❌ Échec log %d\n", currentLogEntry);
    }
  }
}

// ========== FONCTIONS DE DIAGNOSTIC ==========

void verifyLogIntegrity(uint32_t startEntry, uint32_t count) {
  if (!flashInitialized) {
    if (serialEnabled) {
      Serial.println("Flash non initialisée");
    }
    return;
  }
  
  if (serialEnabled) {
    Serial.printf("=== VÉRIFICATION %d entrées depuis %d ===\n", count, startEntry);
  }
  
  uint32_t validEntries = 0;
  uint32_t invalidEntries = 0;
  
  // Recalculer les adresses en mode séquentiel
  uint32_t addr = FLASH_LOG_START_ADDRESS;
  
  for (uint32_t i = 0; i <= startEntry + count - 1 && i < currentLogEntry; i++) {
    // Calculer l'adresse avec alignement
    uint32_t endAddr = addr + sizeof(LogEntry) - 1;
    uint32_t startPage = addr / PAGE_SIZE;
    uint32_t endPage = endAddr / PAGE_SIZE;
    
    if (startPage != endPage) {
      addr = (startPage + 1) * PAGE_SIZE;
    }
    
    // Si c'est dans la plage demandée, vérifier
    if (i >= startEntry) {
      LogEntry entry;
      readFlashData(addr, (uint8_t*)&entry, sizeof(LogEntry));
      
      bool valid = (entry.timestamp != 0xFFFFFFFF);
      for (int j = 0; j < TOTAL_COUNTERS && valid; j++) {
        if (entry.counters[j] == 0xFFFFFFFF) {
          valid = false;
        }
      }
      
      if (valid) {
        validEntries++;
        if (serialEnabled && (i - startEntry) < 3) {
          Serial.printf("✅ Entrée %d (0x%06X): ts=%d\n", i, addr, entry.timestamp);
        }
      } else {
        invalidEntries++;
        if (serialEnabled) {
          Serial.printf("❌ Entrée %d (0x%06X): INVALIDE\n", i, addr);
        }
      }
    }
    
    addr += sizeof(LogEntry);
  }
  
  if (serialEnabled) {
    Serial.printf("Résultat: %d valides, %d invalides\n", validEntries, invalidEntries);
    float pct = (validEntries + invalidEntries > 0) ? 
                (float)validEntries / (validEntries + invalidEntries) * 100.0 : 0;
    Serial.printf("Intégrité: %.1f%%\n", pct);
  }
}

void clearAllLogs() {
  if (!flashInitialized) {
    return;
  }
  
  if (serialEnabled) {
    Serial.println("🗑️ EFFACEMENT COMPLET...");
  }
  
  // Effacer zone de log
  uint32_t sectorsToErase = (FLASH_LOG_SIZE + SECTOR_SIZE - 1) / SECTOR_SIZE;
  
  for (uint32_t i = 0; i < sectorsToErase; i++) {
    uint32_t sectorAddress = FLASH_LOG_START_ADDRESS + (i * SECTOR_SIZE);
    if (serialEnabled) {
      Serial.printf("Effacement %d/%d\n", i + 1, sectorsToErase);
    }
    sectorErase(sectorAddress);
    delay(100);
  }
  
  // Reset complet
  currentLogEntry = 0;
  nextWriteAddress = FLASH_LOG_START_ADDRESS;
  currentLogAddress = FLASH_LOG_START_ADDRESS;
  
  // Effacer métadonnées
  sectorErase(FLASH_METADATA_ADDRESS);
  updateMetadata();
  
  if (serialEnabled) {
    Serial.println("✅ RESET COMPLET terminé");
  }
}

// ========== FONCTIONS EXISTANTES ==========

void sendResponse(const char* message) {
  if (serialEnabled) {
    Serial.print("📤 Série: ");
    Serial.print(message);
  }
  
  if (wifiEnabled && clientConnected) {
    if (serialEnabled) {
      Serial.printf("📤 TCP: %s", message);
    }
    client.print(message);
    client.flush();  // *** IMPORTANT: Forcer l'envoi ***
  }
}


bool connectToServer() {
  if (!wifiEnabled) {
    clientConnected = false;
    return false;
  }

  if (client.connected()) {
    clientConnected = true;
    return true;
  }

  if (WiFi.status() != WL_CONNECTED) {
    clientConnected = false;
    return false;
  }

  if (serialEnabled) {
    Serial.printf("Tentative de connexion au serveur %s:%d...\n",
                  serverIP.toString().c_str(), tcpPort);
  }

  client.setTimeout(10000);
  client.setNoDelay(true);                 // ✅ IMPORTANT

  if (client.connect(serverIP, tcpPort)) {
    clientConnected = true;
    lastTcpOk = millis();                  // ✅ IMPORTANT (sinon dead-timeout te tue)
    lastPingTime = millis();               // optionnel : évite ping immédiat

    delay(200);

    // ✅ Identification (met à jour lastTcpOk si envoi OK)
    sendIdentification();

    if (serialEnabled) Serial.println("✅ TCP connecté + identification envoyée");
    return true;
  }

  clientConnected = false;
  if (serialEnabled) {
    Serial.println("❌ échec connexion serveur");
    Serial.printf("WriteError=%d\n", client.getWriteError());
  }
  return false;
}

// char read_write_reg(char chip, char address, char value, bool read) {
//   // Configuration SPI pour ABeast (comme l'ancien firmware)
//   SPISettings abeastSPISettings(2000000, MSBFIRST, SPI_MODE1); // 2MHz comme DIV8
  
//   uint16_t var1 = (address | 0x80) << 8 | value;
//   if (read)
//     var1 = (address) << 8 | value;
//   char receivedVal = 0;
  
//   // TRANSACTION SPI pour ABeast
//   SPI.beginTransaction(abeastSPISettings);
  
//   switch (chip) {
//     case 0:
//       digitalWrite(CS_PIN_0, LOW);
//       delayMicroseconds(30); // Petit délai comme dans readSingleCounter
//       receivedVal = SPI.transfer16(var1);
//       delayMicroseconds(30);
//       digitalWrite(CS_PIN_0, HIGH);
//       break;
//     case 1:
//       digitalWrite(CS_PIN_1, LOW);
//       delayMicroseconds(30);
//       receivedVal = SPI.transfer16(var1);
//       delayMicroseconds(30);
//       digitalWrite(CS_PIN_1, HIGH);
//       break;
//     case 2:
//       digitalWrite(CS_PIN_2, LOW);
//       delayMicroseconds(30);
//       receivedVal = SPI.transfer16(var1);
//       delayMicroseconds(30);
//       digitalWrite(CS_PIN_2, HIGH);
//       break;
//   }
  
//   SPI.endTransaction();
//   return receivedVal;
// }
uint8_t read_write_reg(uint8_t chip, uint8_t address, uint8_t value, bool read) {
  SPISettings abeastSPISettings(2000000, MSBFIRST, SPI_MODE1);

  uint16_t var1 = ((uint16_t)(read ? address : (address | 0x80)) << 8) | (uint16_t)value;

  int cs_pin = (chip == 0) ? CS_PIN_0 : (chip == 1) ? CS_PIN_1 : CS_PIN_2;

  SPI.beginTransaction(abeastSPISettings);
  digitalWrite(cs_pin, LOW);
  delayMicroseconds(30);
  uint16_t res = SPI.transfer16(var1);
  delayMicroseconds(30);
  digitalWrite(cs_pin, HIGH);
  SPI.endTransaction();

  return (uint8_t)(res & 0xFF);
}

// =========================
//  TCP BINARY PACKET SUPPORT
// =========================
static inline void handleBinaryPacket(uint8_t *p, size_t n) {
  // p = [0]=0x30 [1]=0x31 [2]=chip [3]=cmd [4]=addr [5]=val [6]=0xFF
  if (n < 7) return;

  char chip    = (char)p[2];
  char command = (char)p[3];
  char address = (char)p[4];
  char value   = (char)p[5];

  switch (command) {
    case 0x00: // write register
      read_write_reg(chip, address, value, false);
      sendResponseFast("Ok\n", true);
      break;

    case 0x01: { // read register
      char receivedVal = read_write_reg(chip, address, 0x00, true);
      sendResponseFast("Ok\n", false);
      char tmp[32];
      snprintf(tmp, sizeof(tmp), "%d\n", receivedVal);
      sendResponseFast(tmp, true);
      break;
    }

    default:
      sendResponseFast("Ko\n", true);
      break;
  }

  // sécurité : remonter tous les CS
  digitalWrite(CS_PIN_0, HIGH);
  digitalWrite(CS_PIN_1, HIGH);
  digitalWrite(CS_PIN_2, HIGH);
}

static inline bool tryConsumeBinaryFromTcp() {
  // On ne traite QUE si on a un paquet complet dispo
  // Packet: 0x30 0x31 chip cmd addr val 0xFF  => 7 bytes
  while (client.available() >= 1) {

    int b0 = client.peek();
    if (b0 != 0x30) return false;          // pas binaire en tête

    if (client.available() < 7) return true; // binaire en tête mais pas complet (on attend)

    // On a >=7 bytes -> on peut lire sans risque
    uint8_t pkt[7];
    for (int i = 0; i < 7; i++) pkt[i] = (uint8_t)client.read();

    if (pkt[0] != 0x30 || pkt[1] != 0x31 || pkt[6] != 0xFF) {
      // paquet corrompu -> on jette et on continue (re-sync)
      sendResponseFast("Ko\n", true);
      continue;
    }

    handleBinaryPacket(pkt, 7);
    lastTcpOk = millis();

    // on continue pour voir si d'autres paquets binaires sont collés
    // true = on a traité au moins 1 paquet
    return true;
  }

  return false;
}


void processCommand(String a) {
  if (serialEnabled) {
    Serial.printf("🔧 Commande reçue: len=%d, bytes=[", a.length());
    for (int i = 0; i < a.length(); i++) {
      Serial.printf("0x%02X ", (uint8_t)a[i]);
    }
    Serial.println("]");
  }
  
  if (a.length() < 6) {
    if (serialEnabled) {
      Serial.println("❌ Commande trop courte");
    }
    sprintf(buffer, "Ko\n");
    sendResponse(buffer);
    return;
  }
  
  char receivedVal = 0;
  char chip = a[2];
  char command = a[3];
  char address = a[4];
  char value = a[5];
  
  if (serialEnabled) {
    Serial.printf("📊 Parsed: chip=%d, cmd=0x%02X, addr=%d, val=%d\n", 
                  chip, command, address, value);
  }
  
  switch (command) {
    case 0x00: // write register
      if (serialEnabled) {
        Serial.printf("✏️ Write: chip=%d, addr=%d, val=%d\n", chip, address, value);
      }
      read_write_reg(chip, address, value, 0);
      sprintf(buffer, "Ok\n");
      sendResponse(buffer);
      break;
      
    case 0x01: // read register
      if (serialEnabled) {
        Serial.printf("📖 Read: chip=%d, addr=%d\n", chip, address);
      }
      receivedVal = read_write_reg(chip, address, 0x00, 1);
      if (serialEnabled) {
        Serial.printf("📖 Read result: %d\n", receivedVal);
      }
      sprintf(buffer, "Ok\n");
      sendResponse(buffer);
      sprintf(buffer, "%d\n", receivedVal);
      sendResponse(buffer);
      break;
      
    default:
      if (serialEnabled) {
        Serial.printf("❌ Commande inconnue: 0x%02X\n", command);
      }
      sprintf(buffer, "Ko\n");
      sendResponse(buffer);
      break;
  }
  
  // S'assurer que tous les CS sont HIGH
  digitalWrite(CS_PIN_0, HIGH);
  digitalWrite(CS_PIN_1, HIGH);
  digitalWrite(CS_PIN_2, HIGH);
}


bool processSpecialCommand(String command) {
  if (command.startsWith("ESP_STATUS")) {
    sprintf(buffer, "WiFi: %s, Serial: %s, IP: %s, Gateway: %s, Flash: %s, Logs: %d\n", 
            wifiEnabled ? "ON" : "OFF", 
            serialEnabled ? "ON" : "OFF",
            WiFi.localIP().toString().c_str(),
            WiFi.gatewayIP().toString().c_str(),
            flashInitialized ? "OK" : "ERR",
            currentLogEntry);
    sendResponse(buffer);
    return true;
  }
  else if (command.startsWith("ESP_IDENTIFY")) {
    sendIdentification();   // envoie "ESP_ID:...,DESC:...,MAC:...,IP:...\n"
    return true;            // PAS de "Identification sent\n"
  }

  else if (command.startsWith("ESP_SET_ID ")) {
    String newID = command.substring(11);
    newID.trim();
    if (newID.length() > 0 && newID.length() < 32) {
      ESP_UNIQUE_ID = newID;
      sprintf(buffer, "ID updated to: %s\n", ESP_UNIQUE_ID.c_str());
    } else {
      sprintf(buffer, "Invalid ID format\n");
    }
    sendResponse(buffer);
    return true;
  }
  else if (command == "CNTCSV") {
  sendCountersCsvOnce();
  return true;
}

  else if (command.startsWith("ESP_HEARTBEAT")) {
    sendHeartbeat();
    sprintf(buffer, "Heartbeat sent\n");
    sendResponse(buffer);
    return true;
  }
  else if (command.startsWith("ESP_LOG_STATUS")) {
    sprintf(buffer, "Logging: %s, Interval: %lums, Entries: %d, NextAddr: 0x%06X\n",
            loggingEnabled ? "ON" : "OFF",
            logInterval,
            currentLogEntry,
            nextWriteAddress);
    sendResponse(buffer);
    return true;
  }
  else if (command.startsWith("ESP_MUX_SELECT ")) {
  uint8_t channel = command.substring(15).toInt();
  if (channel <= 3) {
    setMuxChannel(channel);
    sprintf(buffer, "MUX channel %d selected\n", channel);
  } else {
    sprintf(buffer, "Invalid MUX channel (0-3)\n");
  }
  sendResponse(buffer);
  return true;
}
  else if (command.startsWith("ESP_LOG_ENABLE")) {
    loggingEnabled = true;
    sprintf(buffer, "Logging enabled\n");
    sendResponse(buffer);
    return true;
  }
  else if (command.startsWith("ESP_LOG_DISABLE")) {
    loggingEnabled = false;
    sprintf(buffer, "Logging disabled\n");
    sendResponse(buffer);
    return true;
  }
  else if (command.startsWith("ESP_LOG_INTERVAL ")) {
    unsigned long newInterval = command.substring(17).toInt();
    if (newInterval >= 1000 && newInterval <= 3600000) {
      logInterval = newInterval;
      sprintf(buffer, "Log interval set to %lums\n", logInterval);
    } else {
      sprintf(buffer, "Invalid interval (1000-3600000ms)\n");
    }
    sendResponse(buffer);
    return true;
  }
  else if (command.startsWith("ESP_LOG_READ ")) {
  int spacePos = command.indexOf(' ', 13);
  if (spacePos > 0) {
    uint32_t startEntry = command.substring(13, spacePos).toInt();
    uint32_t count = command.substring(spacePos + 1).toInt();

    sprintf(buffer, "LOG_DATA_START %d %d\n", startEntry, count);
    sendResponseFast(buffer, true);  // flush au début

    // Calcul séquentiel des adresses
    uint32_t addr = FLASH_LOG_START_ADDRESS;

// 1) se positionner sur startEntry
  for (uint32_t i = 0; i < startEntry && i < currentLogEntry; i++) {
    addr = advanceAddr(addr);
  }

  // 2) lire count entrées à partir de là
  for (uint32_t k = 0; k < count && (startEntry + k) < currentLogEntry; k++) {
    LogEntry entry;
    readFlashData(addr, (uint8_t*)&entry, sizeof(LogEntry));

    char line[256];
    int len = snprintf(line, sizeof(line), "LOG_ENTRY %u %u", (startEntry + k), entry.timestamp);
    for (int j = 0; j < TOTAL_COUNTERS && len < (int)sizeof(line) - 16; j++) {
      len += snprintf(line + len, sizeof(line) - len, " %u", entry.counters[j]);
    }
    line[len++] = '\n';
    line[len] = '\0';

    sendResponseFast(line, false);
    if (((startEntry + k) & 31) == 0) { sendResponseFast("", true); delay(0); }

    addr = advanceAddr(addr);
  }



    // for (uint32_t i = 0; i <= startEntry + count - 1 && i < currentLogEntry; i++) {
    //   // Calculer adresse avec alignement
    //   uint32_t endAddr  = addr + sizeof(LogEntry) - 1;
    //   uint32_t startPage = addr / PAGE_SIZE;
    //   uint32_t endPage   = endAddr / PAGE_SIZE;
    //   if (startPage != endPage) {
    //     addr = (startPage + 1) * PAGE_SIZE;
    //   }

    //   if (i >= startEntry) {
    //     LogEntry entry;
    //     readFlashData(addr, (uint8_t*)&entry, sizeof(LogEntry));

    //     // Construire UNE SEULE ligne
    //     char line[256];
    //     int len = snprintf(line, sizeof(line), "LOG_ENTRY %u %u", i, entry.timestamp);
    //     for (int j = 0; j < TOTAL_COUNTERS && len < (int)sizeof(line) - 16; j++) {
    //       len += snprintf(line + len, sizeof(line) - len, " %u", entry.counters[j]);
    //     }
    //     if (len < (int)sizeof(line) - 2) {
    //       line[len++] = '\n';
    //       line[len] = '\0';
    //     }
    //     sendResponseFast(line, false);

    //     // (Optionnel) petit flush périodique pour vider le buffer TCP
    //     if ((i & 31) == 0) { sendResponseFast("", true); delay(0); }
    //   }

    //   addr += sizeof(LogEntry);
    // }

    sendResponseFast("LOG_DATA_END\n", true);   // flush en fin de bloc
  } else {
    sprintf(buffer, "Usage: ESP_LOG_READ <start> <count>\n");
    sendResponseFast(buffer, true);
  }
  return true;
}
else if (command.startsWith("ESP_LOG_LATEST ")) {
    uint32_t count = command.substring(15).toInt();
    if (count > 100) count = 100;

    uint32_t startEntry = (currentLogEntry >= count) ? (currentLogEntry - count) : 0;

    char hdr[64];
    snprintf(hdr, sizeof(hdr), "LOG_DATA_START %u %u\n", startEntry, count);
    sendResponseFast(hdr, true);

    uint32_t addr = FLASH_LOG_START_ADDRESS;

    // 1) se positionner sur startEntry
    for (uint32_t i = 0; i < startEntry && i < currentLogEntry; i++) {
      addr = advanceAddr(addr);
    }

    // 2) lire count entrées
    for (uint32_t k = 0; k < count && (startEntry + k) < currentLogEntry; k++) {
      LogEntry entry;
      readFlashData(addr, (uint8_t*)&entry, sizeof(LogEntry));

      char line[256];
      int len = snprintf(line, sizeof(line), "LOG_ENTRY %u %u", (startEntry + k), entry.timestamp);
      for (int j = 0; j < TOTAL_COUNTERS && len < (int)sizeof(line) - 16; j++) {
        len += snprintf(line + len, sizeof(line) - len, " %u", entry.counters[j]);
      }
      line[len++] = '\n';
      line[len] = '\0';

      sendResponseFast(line, false);
      if (((startEntry + k) & 31) == 0) { sendResponseFast("", true); yield(); }

      addr = advanceAddr(addr);
    }

    sendResponseFast("LOG_DATA_END\n", true);
    return true;
  }


  else if (command.startsWith("ESP_LOG_CLEAR")) {
    currentLogEntry = 0;
    nextWriteAddress = FLASH_LOG_START_ADDRESS;
    currentLogAddress = FLASH_LOG_START_ADDRESS;
    sectorErase(FLASH_METADATA_ADDRESS);
    updateMetadata();
    sprintf(buffer, "Logs cleared\n");
    sendResponse(buffer);
    return true;
  }
  else if (command.startsWith("ESP_LOG_CLEAR_ALL")) {
    clearAllLogs();
    sprintf(buffer, "All logs completely erased\n");
    sendResponse(buffer);
    return true;
  }

  // else if (command.startsWith("ESP_FLASH_TEST")) {
  //   if (testFlashID()) {
  //     sprintf(buffer, "Flash test OK\n");
  //   } else {
  //     sprintf(buffer, "Flash test FAILED\n");
  //   }
  //   sendResponse(buffer);
  //   return true;
  // }

  else if (command.startsWith("ESP_WIFI_ON")) {
    wifiEnabled = true;
    // Réactiver WiFi
    if (WiFi.status() != WL_CONNECTED) {
      connectToWiFi();
    }
    sprintf(buffer, "WiFi mode enabled\n");
    sendResponse(buffer);
    return true;
  }
  else if (command.startsWith("ESP_WIFI_OFF")) {
    wifiEnabled = false;
    if (client.connected()) {
      client.stop();
    }
    clientConnected = false;
    sprintf(buffer, "WiFi mode disabled\n");
    sendResponse(buffer);
    return true;
  }
  else if (command.startsWith("ESP_SERIAL_ON")) {
    serialEnabled = true;
    sprintf(buffer, "Serial mode enabled\n");
    sendResponse(buffer);
    return true;
  }
  
  else if (command.startsWith("ESP_SERIAL_OFF")) {
    if (!wifiEnabled) {
      sprintf(buffer, "Cannot disable Serial when WiFi is disabled\n");
      sendResponse(buffer);
    } else {
      serialEnabled = false;
      sprintf(buffer, "Serial mode disabled\n");
      sendResponse(buffer);
    }
    return true;
  }
  else if (command.startsWith("ESP_NETWORK_INFO")) {
    sprintf(buffer, "Network Information:\n");
    sendResponse(buffer);
    sprintf(buffer, "  SSID: %s\n", WiFi.SSID().c_str());
    sendResponse(buffer);
    sprintf(buffer, "  IP: %s\n", WiFi.localIP().toString().c_str());
    sendResponse(buffer);
    sprintf(buffer, "  Gateway: %s\n", WiFi.gatewayIP().toString().c_str());
    sendResponse(buffer);
    sprintf(buffer, "  Subnet: %s\n", WiFi.subnetMask().toString().c_str());
    sendResponse(buffer);
    sprintf(buffer, "  RSSI: %d dBm\n", WiFi.RSSI());
    sendResponse(buffer);
    sprintf(buffer, "  Server IP: %s:%d\n", serverIP.toString().c_str(), tcpPort);
    sendResponse(buffer);
    return true;
  }
  
  return false;
}
void sendIdentification() {
  char msg[256];
  snprintf(msg, sizeof(msg),
           "ESP_ID:%s,DESC:%s,MAC:%s,IP:%s\n",
           ESP_UNIQUE_ID.c_str(),
           ESP_DESCRIPTION.c_str(),
           WiFi.macAddress().c_str(),
           WiFi.localIP().toString().c_str());

  sendResponseFast(msg, true);   // ✅ met lastTcpOk à jour si OK

  if (serialEnabled) Serial.printf("📤 Identification: %s", msg);
}




// void sendHeartbeat() {
//   if (wifiEnabled && clientConnected) {
//     sprintf(buffer, "ESP_HEARTBEAT:%s,UPTIME:%lu,FREE_HEAP:%u,LOGS:%u\n",
//             ESP_UNIQUE_ID.c_str(),
//             millis() / 1000,
//             ESP.getFreeHeap(),
//             currentLogEntry);
//     client.print(buffer);
//   }
// }
void sendHeartbeat() {
  char msg[256];
  snprintf(msg, sizeof(msg),
    "ESP_HEARTBEAT:%s,UPTIME:%lu,FREE_HEAP:%u,LOGS:%u\n",
    ESP_UNIQUE_ID.c_str(), millis()/1000, ESP.getFreeHeap(), currentLogEntry);

  sendResponseFast(msg, true);
}

void connectToWiFi() {
  if (!wifiEnabled) return;

  if (WiFi.status() != WL_CONNECTED) {
    if (serialEnabled) Serial.printf("Connexion au WiFi %s...\n", ssid);

    // RESET propre du Wi-Fi
    WiFi.persistent(false);
    WiFi.mode(WIFI_STA);
    WiFi.disconnect(true);
    delay(200);
    if (!WiFi.config(local_IP, gateway, subnet, dns1)) {
      if (serialEnabled) Serial.println("❌ WiFi.config() failed");
    }

    WiFi.begin(ssid, password);

    unsigned long startTime = millis();
    const unsigned long timeout = 30000;

    while (WiFi.status() != WL_CONNECTED && millis() - startTime < timeout) {
      delay(300);
      if (serialEnabled) Serial.print(".");
    }
    if (serialEnabled) Serial.println();

    if (WiFi.status() == WL_CONNECTED) {
      if (serialEnabled) {
        Serial.printf("connecté ! SSID=%s  IP=%s  RSSI=%d dBm  CH=%d  BSSID=%s\n",
          WiFi.SSID().c_str(),
          WiFi.localIP().toString().c_str(),
          WiFi.RSSI(),
          wifi_get_channel(),
          WiFi.BSSIDstr().c_str());
      }
      delay(1500);
      connectToServer(); // serverIP doit être 192.168.137.9
    } else {
      if (serialEnabled) {
        Serial.printf("échec WiFi: status=%d\n", WiFi.status());
        WiFi.printDiag(Serial);
      }
    }
  }
}


// ========== SETUP FINAL ==========

void setup() {
  if (LED_PIN >= 0) {
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, HIGH);
  }

 // --- Réactive le logging, mais on laisse la commande décider
loggingEnabled = true;      // autorise les commandes ESP_LOG_ENABLE/DISABLE
flashInitialized = false;   // sera mis à true uniquement si initializeFlash() OK


  if (serialEnabled) {
    Serial.begin(115200);
    delay(200);
    Serial.println();
    Serial.println("===== BOOT =====");
    Serial.printf("Reset reason: %s\n", ESP.getResetReason().c_str());
    Serial.printf("Reset info  : %s\n", ESP.getResetInfo().c_str());
    Serial.printf("Free heap   : %u\n", ESP.getFreeHeap());
    Serial.println("================");



    while (!Serial) delay(200);
    Serial.flush();
    Serial.println("=== ESP8266 FLASH LOGGING SÉQUENTIEL ULTIME CORRIGÉ ===");
    Serial.printf("Configuration réseau: 192.168.50.x\n");
    Serial.printf("Serveur cible: %s:%d\n", serverIP.toString().c_str(), tcpPort);
  }
  
  // Initialisation SPI
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
  digitalWrite(MUX_A0, LOW);
  digitalWrite(MUX_A1, LOW);
  
  // Configure SPI pour stabilité maximale
  SPI.setClockDivider(SPI_CLOCK_DIV64);
  SPI.setDataMode(SPI_MODE1);
  SPI.setBitOrder(MSBFIRST);
  
  // Initialiser flash en mode séquentiel
  if (serialEnabled) {
    Serial.println("Initialisation flash mode SÉQUENTIEL...");
  }
  
  if (initializeFlash()) {
    if (serialEnabled) {
      Serial.println("✅ Flash mode SÉQUENTIEL initialisée");
    }
  } else {
    if (serialEnabled) {
      Serial.println("❌ Erreur flash - logging désactivé");
    }
    loggingEnabled = false;
  }
    // === APPLIQUE LA CONFIG "EN DUR" AU DÉMARRAGE ===
  delay(500);                 // laissons l'ABeast s'initialiser
  setMuxChannel(0);           // canal MUX par défaut (ajuste si besoin)
  // lecture "dummy" pour réveiller le bus
  (void) read_write_reg(0, 2, 0x00, /*read=*/true);
  (void) read_write_reg(1, 2, 0x00, /*read=*/true);
  (void) read_write_reg(2, 2, 0x00, /*read=*/true);

  if (serialEnabled) Serial.println("🔧 Application config ABeast par défaut (firmware)...");
  applyDefaultConfigABeasts(/*verify=*/true);

  // *** IDENTIFICATION ESP - UNE SEULE FOIS AU DÉMARRAGE ***
  if (serialEnabled) {
    Serial.println("=== IDENTIFICATION ESP ===");
    Serial.printf("ID: %s\n", ESP_UNIQUE_ID.c_str());
    Serial.printf("Description: %s\n", ESP_DESCRIPTION.c_str());
    Serial.printf("MAC: %s\n", WiFi.macAddress().c_str());
    Serial.println("==========================");
  }
  
  // Initialisation WiFi si activé
  if (wifiEnabled) {
    connectToWiFi();
  }
  
  if (serialEnabled) {
    Serial.println("ESP8266 Ready - MODE SÉQUENTIEL CORRIGÉ");
  }
}

// ========== LOOP FINAL ==========

void loop() {
  unsigned long now = millis();

  // =========================
  // 1) LOGGING (peut être long)
  // =========================
  if (flashInitialized && loggingEnabled && (now - lastLogTime >= logInterval)) {
    lastLogTime = now;
    logCountersSequential();
    yield(); // important ESP8266
  }

// =========================
// 2) MAINTENANCE TCP
// =========================

if (wifiEnabled && clientConnected) {

  if (!client.connected()) {
    if (serialEnabled) Serial.println("⚠️ TCP socket closed by server");
    client.stop();
    clientConnected = false;
  }
  else {
    // ping périodique uniquement (optionnel)
    if (now - lastPingTime >= pingInterval) {
      lastPingTime = now;
      sendResponseFast("PING\n", true);
    }
  }
}


  // =========================
  // 3) SURVEILLANCE WIFI (reco si WiFi down)
  // =========================
  if (wifiEnabled && (now - lastWifiCheck >= wifiCheckInterval)) {
    lastWifiCheck = now;

    if (WiFi.status() != WL_CONNECTED) {
      if (serialEnabled) Serial.println("WiFi déconnecté, tentative de reconnexion...");
      connectToWiFi();
    }
  }

  // =========================
  // 4) RECONNEXION TCP SI NECESSAIRE
  // =========================
  if (wifiEnabled && (WiFi.status() == WL_CONNECTED) && !clientConnected) {
    if (now - lastReconnectAttempt >= reconnectInterval) {
      lastReconnectAttempt = now;
      if (serialEnabled) Serial.println("Tentative de reconnexion au serveur TCP...");
      connectToServer(); // met lastTcpOk si connect OK
    }
  }

  // =========================
  // 5) COMMANDES SERIE
  // =========================
  if (serialEnabled && Serial.available()) {
    String serialData = Serial.readString();
    serialData.trim();

    if (serialData.startsWith("ESP_")) {
      processSpecialCommand(serialData);
    }
    else if (serialData.length() >= 6 && serialData[0] == 0x30 && serialData[1] == 0x31) {
      sendResponse("Ok\n");
      processCommand(serialData);
    }
    yield();
  }

// =========================
// 6) COMMANDES TCP (binaire ou texte) - FIX FINAL
// =========================
if (wifiEnabled && clientConnected && client.connected()) {

  static uint8_t binBuf[7];
  static uint8_t binPos = 0;
  static bool binMode = false;

  static char line[256];
  static int idx = 0;

  while (client.available()) {
    uint8_t b = (uint8_t)client.read();

    // --- détection binaire ---
    if (!binMode) {
      // tentative de démarrer un paquet binaire
      if (binPos == 0) {
        if (b == 0x30) { binBuf[binPos++] = b; continue; }
      } else if (binPos == 1) {
        if (b == 0x31) {
          binBuf[binPos++] = b;
          binMode = true;          // ✅ on bascule en mode binaire
          continue;
        } else {
          // faux départ: le 0x30 était juste un '0' ASCII -> on le remet en TEXTE
          char c0 = (char)binBuf[0];
          if (c0 != '\r') {
            if (c0 == '\n' || idx >= 254) { line[idx] = '\0'; idx = 0; }
            else line[idx++] = c0;
          }
          binPos = 0;
          // et on traite b comme texte (on tombe plus bas)
        }
      }
    }

    if (binMode) {
      binBuf[binPos++] = b;
      if (binPos >= 7) {
        // paquet complet
        if (binBuf[0] == 0x30 && binBuf[1] == 0x31 && binBuf[6] == 0xFF) {
          handleBinaryPacket(binBuf, 7);
          lastTcpOk = millis();
        } else {
          sendResponseFast("Ko\n", true);
        }
        binPos = 0;
        binMode = false;
      }
      continue;
    }

    // --- parser TEXTE ---
    char c = (char)b;
    if (c == '\r') continue;

    if (c == '\n' || idx >= 254) {
      line[idx] = '\0';
      idx = 0;
      lastTcpOk = millis();

      if (strcmp(line, "PONG") == 0) {
        // ignore
      } else if (strlen(line) > 0) {
        if (!processSpecialCommand(String(line))) {
          sendResponseFast("ERR unknown\n", true);
        }
      }
    } else {
      line[idx++] = c;
    }
  }
}

// =========================
// 7) Fin de loop: respiration watchdog
// =========================
yield();
}

// if (wifiEnabled && clientConnected && client.connected()) {

//   static char line[256];
//   static int idx = 0;

//   while (client.available()) {

//     // --- 1) Détection paquet binaire: 0x30 0x31 + 5 bytes + 0xFF ---
//     if (client.available() >= 2) {
//       int b0 = client.peek();
//       if (b0 == 0x30) {
//         // lire le 2e byte sans perdre le 1er ? -> on consomme proprement :
//         uint8_t hdr0 = (uint8_t)client.read();     // 0x30
//         uint8_t hdr1 = (uint8_t)client.peek();     // regarde le suivant sans consommer

//         if (hdr1 == 0x31) {
//           // on a bien 0x30 0x31, on attend le reste
//           if (client.available() < 6) {
//             // pas assez de bytes encore (on a déjà consommé 0x30)
//             // => on remet ce 0x30 dans le flux ? impossible.
//             // Donc: on attend très court que les bytes arrivent.
//             unsigned long t0 = millis();
//             while (client.available() < 6 && (millis() - t0) < 50) yield();
//           }

//           if (client.available() >= 6) {
//             uint8_t pkt[7];
//             pkt[0] = hdr0;                         // 0x30
//             pkt[1] = (uint8_t)client.read();       // 0x31 (consommé)
//             for (int i = 2; i < 7; i++) pkt[i] = (uint8_t)client.read();

//             // (option debug) pour voir si le binaire arrive bien:
//             // sendResponseFast("BIN\n", false);

//             // exécuter
//             uint8_t chip    = pkt[2];
//             uint8_t command = pkt[3];
//             uint8_t address = pkt[4];
//             uint8_t value   = pkt[5];
//             uint8_t endb    = pkt[6];

//             if (endb != 0xFF) {
//               sendResponseFast("Ko\n", true);
//             } else {
//               if (command == 0x00) { // write
//                 read_write_reg((char)chip, (char)address, (char)value, false);
//                 sendResponseFast("Ok\n", true);
//               }
//               else if (command == 0x01) { // read
//                 char receivedVal = read_write_reg((char)chip, (char)address, (char)0x00, true);
//                 sendResponseFast("Ok\n", false);
//                 char tmp[32];
//                 snprintf(tmp, sizeof(tmp), "%d\n", receivedVal);
//                 sendResponseFast(tmp, true);
//               }
//               else {
//                 sendResponseFast("Ko\n", true);
//               }

//               digitalWrite(CS_PIN_0, HIGH);
//               digitalWrite(CS_PIN_1, HIGH);
//               digitalWrite(CS_PIN_2, HIGH);
//             }

//             lastTcpOk = millis();
//             continue; // on repart lire le reste du flux
//           }

//           // si on n'a pas réussi à compléter -> on abandonne ce tour
//           // (mais en pratique, avec sendall, ça arrive toujours en bloc)
//           continue;
//         }
//         else {
//           // faux header: on traite hdr0 comme texte '0'
//           char c = (char)hdr0;
//           if (c == '\n' || idx >= 254) {
//             line[idx] = '\0'; idx = 0;
//             if (strlen(line) > 0) {
//               if (!processSpecialCommand(String(line))) sendResponseFast("ERR unknown\n", true);
//             }
//           } else {
//             line[idx++] = c;
//           }
//           continue;
//         }
//       }
//     }

//     // --- 2) Parser texte classique ligne par ligne ---
//     char c = (char)client.read();

//     if (c == '\n' || idx >= 254) {
//       line[idx] = '\0';
//       idx = 0;
//       lastTcpOk = millis();

//       if (strcmp(line, "PONG") == 0) {
//         // ignore
//       }
//       else if (strlen(line) > 0) {
//         if (!processSpecialCommand(String(line))) {
//           sendResponseFast("ERR unknown\n", true);
//         }
//       }
//     }
//     else {
//       line[idx++] = c;
//     }
//   }
// }

//   // =========================
//   // 7) Fin de loop: respiration watchdog
//   // =========================
//   yield();
// }

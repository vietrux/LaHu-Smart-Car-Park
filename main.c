/**
 * Smart Car Park System - STM32 Controller
 * 
 * Controls vehicle barrier system with:
 * - LM393 sensor for vehicle detection (PA0)
 * - SG90 servo for barrier control (PB6)
 * - SSD1306 OLED display via I2C (PB8/PB9)
 * - UART communication with Raspberry Pi (PA2/PA3)
 */

#include "main.h"
#include "u8g2.h"
#include <string.h>
#include <stdbool.h>

/* Private definitions */
#define UART_TIMEOUT 10  // UART timeout in ms
#define DEBOUNCE_TIME 50 // Debounce time in ms
#define PACKET_START 0xAA
#define BUFFER_SIZE 32

/* Event IDs */
#define EVENT_DISPLAY 0x01
#define EVENT_SERVO 0x02
#define EVENT_CAR_DETECT 0x03
#define EVENT_LP_STATUS 0x04
#define EVENT_PARK_FULL 0x05

/* Servo positions */
#define SERVO_CLOSED 0
#define SERVO_OPEN 90

/* Private variables */
UART_HandleTypeDef huart2;
TIM_HandleTypeDef htim3;
I2C_HandleTypeDef hi2c1;

u8g2_t u8g2; // OLED display instance

uint8_t rxBuffer[BUFFER_SIZE];
uint8_t txBuffer[BUFFER_SIZE];
uint8_t carDetected = 0;
uint8_t lastCarDetected = 0;
uint32_t lastDebounceTime = 0;
uint32_t lastDetectionSendTime = 0;

/* Private function prototypes */
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_USART2_UART_Init(void);
static void MX_TIM3_Init(void);
static void MX_I2C1_Init(void);

void OLED_Init(void);
void OLED_Display(const char* message);
void SetServoAngle(uint8_t angle);
uint8_t CalculateCRC8(uint8_t *data, uint8_t length);
void SendPacket(uint8_t eventId, uint8_t *data, uint8_t dataLength);
void ProcessReceivedPacket(uint8_t *buffer);

/* u8g2 callbacks */
uint8_t u8x8_stm32_gpio_and_delay(U8X8_UNUSED u8x8_t *u8x8, U8X8_UNUSED uint8_t msg, U8X8_UNUSED uint8_t arg_int, U8X8_UNUSED void *arg_ptr);
uint8_t u8x8_byte_stm32_hw_i2c(u8x8_t *u8x8, uint8_t msg, uint8_t arg_int, void *arg_ptr);

/**
 * @brief  Main program.
 */
int main(void)
{
  HAL_Init();
  SystemClock_Config();

  /* Initialize all peripherals */
  MX_GPIO_Init();
  MX_USART2_UART_Init();
  MX_TIM3_Init();
  MX_I2C1_Init();

  /* Initialize OLED display */
  OLED_Init();
  OLED_Display("Ready");

  /* Start PWM for servo */
  HAL_TIM_PWM_Start(&htim3, TIM_CHANNEL_1);
  SetServoAngle(SERVO_CLOSED);

  /* Start UART reception in interrupt mode */
  HAL_UART_Receive_IT(&huart2, rxBuffer, 1);

  /* Main loop */
  while (1)
  {
    /* Check car detection sensor with debounce */
    uint8_t currentSensorState = HAL_GPIO_ReadPin(GPIOA, GPIO_PIN_0);
    
    if (currentSensorState != lastCarDetected) {
      lastDebounceTime = HAL_GetTick();
    }
    
    if ((HAL_GetTick() - lastDebounceTime) > DEBOUNCE_TIME) {
      if (carDetected != currentSensorState) {
        carDetected = currentSensorState;
        
        /* Send car detection status to Pi */
        SendPacket(EVENT_CAR_DETECT, &carDetected, 1);
      }
    }
    
    lastCarDetected = currentSensorState;
    
    /* Send car detection status periodically (every 1s) */
    if ((HAL_GetTick() - lastDetectionSendTime) > 1000) {
      SendPacket(EVENT_CAR_DETECT, &carDetected, 1);
      lastDetectionSendTime = HAL_GetTick();
    }
  }
}

/**
 * @brief UART Receive complete callback
 */
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
  static uint8_t packetBuffer[BUFFER_SIZE];
  static uint8_t packetIndex = 0;
  static uint8_t packetState = 0;
  static uint8_t packetLength = 0;
  
  if (huart->Instance == USART2) {
    /* State machine to parse incoming packets */
    switch (packetState) {
      case 0: /* Wait for start byte */
        if (rxBuffer[0] == PACKET_START) {
          packetBuffer[0] = PACKET_START;
          packetIndex = 1;
          packetState = 1;
        }
        break;
      
      case 1: /* Get length */
        packetLength = rxBuffer[0];
        packetBuffer[packetIndex++] = packetLength;
        packetState = 2;
        break;
      
      case 2: /* Get data */
        packetBuffer[packetIndex++] = rxBuffer[0];
        
        /* Check if we have the full packet */
        if (packetIndex >= (packetLength + 3)) { // Start + Length + Data + CRC
          ProcessReceivedPacket(packetBuffer);
          packetState = 0;
          packetIndex = 0;
        }
        break;
    }
    
    /* Continue UART reception */
    HAL_UART_Receive_IT(&huart2, rxBuffer, 1);
  }
}

/**
 * @brief Process a complete received packet
 */
void ProcessReceivedPacket(uint8_t *buffer)
{
  uint8_t length = buffer[1];
  uint8_t eventId = buffer[2];
  uint8_t *data = &buffer[3];
  uint8_t receivedCRC = buffer[2 + length];
  uint8_t calculatedCRC = CalculateCRC8(&buffer[2], length);
  
  /* Verify CRC */
  if (receivedCRC == calculatedCRC) {
    /* Send "OK" response */
    strcpy((char*)txBuffer, "OK\n");
    HAL_UART_Transmit(&huart2, txBuffer, 3, UART_TIMEOUT);
    
    /* Process the packet */
    switch (eventId) {
      case EVENT_DISPLAY:
        /* Display message on OLED */
        OLED_Display((char*)data);
        break;
      
      case EVENT_SERVO:
        /* Set servo angle */
        SetServoAngle(data[0]);
        break;
      
      case EVENT_LP_STATUS:
        /* Handle license plate status */
        if (data[0] == 1) {
          /* Registered plate, open barrier */
          SetServoAngle(SERVO_OPEN);
        } else {
          /* Unregistered plate, barrier remains closed */
          SetServoAngle(SERVO_CLOSED);
        }
        break;
      
      case EVENT_PARK_FULL:
        /* Handle parking lot full status */
        if (data[0] == 1) {
          OLED_Display("Lot Full");
        } else {
          OLED_Display("Spaces Available");
        }
        break;
    }
  } else {
    /* Send "ERR" response */
    strcpy((char*)txBuffer, "ERR\n");
    HAL_UART_Transmit(&huart2, txBuffer, 4, UART_TIMEOUT);
  }
}

/**
 * @brief Send a packet to the Raspberry Pi
 */
void SendPacket(uint8_t eventId, uint8_t *data, uint8_t dataLength)
{
  uint8_t packet[BUFFER_SIZE];
  uint8_t index = 0;
  
  /* Construct packet */
  packet[index++] = PACKET_START;    /* Start byte */
  packet[index++] = dataLength + 1;  /* Length (event ID + data) */
  packet[index++] = eventId;         /* Event ID */
  
  /* Copy data */
  for (uint8_t i = 0; i < dataLength; i++) {
    packet[index++] = data[i];
  }
  
  /* Calculate and append CRC */
  packet[index] = CalculateCRC8(&packet[2], dataLength + 1);
  
  /* Send packet */
  HAL_UART_Transmit(&huart2, packet, index + 1, UART_TIMEOUT);
}

/**
 * @brief Initialize OLED display
 */
void OLED_Init(void)
{
  u8g2_Setup_ssd1306_i2c_128x64_noname_f(
    &u8g2, 
    U8G2_R0, 
    u8x8_byte_stm32_hw_i2c, 
    u8x8_stm32_gpio_and_delay
  );
  
  u8g2_InitDisplay(&u8g2);
  u8g2_SetPowerSave(&u8g2, 0);
  u8g2_ClearBuffer(&u8g2);
  u8g2_SetFont(&u8g2, u8g2_font_ncenB08_tr);
}

/**
 * @brief Display message on OLED
 */
void OLED_Display(const char* message)
{
  u8g2_ClearBuffer(&u8g2);
  u8g2_SetFont(&u8g2, u8g2_font_ncenB08_tr);
  u8g2_DrawStr(&u8g2, 0, 16, message);
  u8g2_SendBuffer(&u8g2);
}

/**
 * @brief Set servo angle
 */
void SetServoAngle(uint8_t angle)
{
  /* Ensure angle is within range */
  if (angle > 180) angle = 180;
  
  /* Convert angle to pulse width
   * 0° = 1ms pulse (50 Hz => 1ms/20ms = 5% duty cycle)
   * 90° = 1.5ms pulse (50 Hz => 1.5ms/20ms = 7.5% duty cycle)
   * 180° = 2ms pulse (50 Hz => 2ms/20ms = 10% duty cycle)
   */
  uint32_t pulseWidth = 50 + (angle * 100 / 180); /* 50-150 for 1ms-2ms */
  
  /* Update PWM duty cycle */
  __HAL_TIM_SET_COMPARE(&htim3, TIM_CHANNEL_1, pulseWidth);
}

/**
 * @brief Calculate CRC8 checksum
 */
uint8_t CalculateCRC8(uint8_t *data, uint8_t length)
{
  uint8_t crc = 0;
  uint8_t i, j;
  
  for (i = 0; i < length; i++) {
    crc ^= data[i];
    for (j = 0; j < 8; j++) {
      if (crc & 0x80) {
        crc = (crc << 1) ^ 0x07; /* Polynomial 0x07 */
      } else {
        crc = crc << 1;
      }
    }
  }
  
  return crc;
}

/**
 * @brief u8g2 GPIO and delay callback
 */
uint8_t u8x8_stm32_gpio_and_delay(U8X8_UNUSED u8x8_t *u8x8, U8X8_UNUSED uint8_t msg, U8X8_UNUSED uint8_t arg_int, U8X8_UNUSED void *arg_ptr)
{
  switch (msg) {
    case U8X8_MSG_DELAY_MILLI:
      HAL_Delay(arg_int);
      break;
    default:
      break;
  }
  return 1;
}

/**
 * @brief u8g2 I2C callback
 */
uint8_t u8x8_byte_stm32_hw_i2c(u8x8_t *u8x8, uint8_t msg, uint8_t arg_int, void *arg_ptr)
{
  static uint8_t buffer[32];
  static uint8_t buf_idx;
  uint8_t *data;
  
  switch (msg) {
    case U8X8_MSG_BYTE_SEND:
      data = (uint8_t *)arg_ptr;
      while (arg_int > 0) {
        buffer[buf_idx++] = *data;
        data++;
        arg_int--;
      }
      break;
    
    case U8X8_MSG_BYTE_INIT:
      break;
    
    case U8X8_MSG_BYTE_SET_DC:
      break;
    
    case U8X8_MSG_BYTE_START_TRANSFER:
      buf_idx = 0;
      break;
    
    case U8X8_MSG_BYTE_END_TRANSFER:
      HAL_I2C_Master_Transmit(&hi2c1, u8x8_GetI2CAddress(u8x8) << 1, buffer, buf_idx, 1000);
      break;
    
    default:
      return 0;
  }
  return 1;
}

/**
 * @brief System Clock Configuration
 */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /* Configure main, PLL oscillators */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI;
  RCC_OscInitStruct.HSIState = RCC_HSI_ON;
  RCC_OscInitStruct.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSI_DIV2;
  RCC_OscInitStruct.PLL.PLLMUL = RCC_PLL_MUL16;
  HAL_RCC_OscConfig(&RCC_OscInitStruct);

  /* Configure CPU, AHB, APB bus clocks */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV2;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;
  HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_2);
}

/**
 * @brief USART2 Initialization Function
 */
static void MX_USART2_UART_Init(void)
{
  huart2.Instance = USART2;
  huart2.Init.BaudRate = 115200;
  huart2.Init.WordLength = UART_WORDLENGTH_8B;
  huart2.Init.StopBits = UART_STOPBITS_1;
  huart2.Init.Parity = UART_PARITY_NONE;
  huart2.Init.Mode = UART_MODE_TX_RX;
  huart2.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart2.Init.OverSampling = UART_OVERSAMPLING_16;
  HAL_UART_Init(&huart2);
}

/**
 * @brief TIM3 Initialization Function for PWM
 */
static void MX_TIM3_Init(void)
{
  TIM_MasterConfigTypeDef sMasterConfig = {0};
  TIM_OC_InitTypeDef sConfigOC = {0};

  /* Timer base configuration - 50Hz for servo control */
  htim3.Instance = TIM3;
  htim3.Init.Prescaler = 64-1;  /* 64MHz / 64 = 1MHz */
  htim3.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim3.Init.Period = 20000-1;  /* 1MHz / 20000 = 50Hz */
  htim3.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  HAL_TIM_PWM_Init(&htim3);

  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  HAL_TIMEx_MasterConfigSynchronization(&htim3, &sMasterConfig);

  /* PWM channel configuration */
  sConfigOC.OCMode = TIM_OCMODE_PWM1;
  sConfigOC.Pulse = 1500;  /* Default 1.5ms pulse (90 degrees) */
  sConfigOC.OCPolarity = TIM_OCPOLARITY_HIGH;
  sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;
  HAL_TIM_PWM_ConfigChannel(&htim3, &sConfigOC, TIM_CHANNEL_1);
}

/**
 * @brief I2C1 Initialization Function
 */
static void MX_I2C1_Init(void)
{
  hi2c1.Instance = I2C1;
  hi2c1.Init.ClockSpeed = 400000;  /* 400KHz Fast mode */
  hi2c1.Init.DutyCycle = I2C_DUTYCYCLE_2;
  hi2c1.Init.OwnAddress1 = 0;
  hi2c1.Init.AddressingMode = I2C_ADDRESSINGMODE_7BIT;
  hi2c1.Init.DualAddressMode = I2C_DUALADDRESS_DISABLE;
  hi2c1.Init.OwnAddress2 = 0;
  hi2c1.Init.GeneralCallMode = I2C_GENERALCALL_DISABLE;
  hi2c1.Init.NoStretchMode = I2C_NOSTRETCH_DISABLE;
  HAL_I2C_Init(&hi2c1);
}

/**
 * @brief GPIO Initialization Function
 */
static void MX_GPIO_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};

  /* GPIO Ports Clock Enable */
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();

  /* Configure GPIO pin for LM393 sensor */
  GPIO_InitStruct.Pin = GPIO_PIN_0;
  GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
  GPIO_InitStruct.Pull = GPIO_PULLDOWN;
  HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);
}

/**
 * @brief  This function handles System tick timer.
 */
void SysTick_Handler(void)
{
  HAL_IncTick();
}

#ifdef  USE_FULL_ASSERT
/**
 * @brief  Reports the name of the source file and the source line number
 *         where the assert_param error has occurred.
 * @param  file: pointer to the source file name
 * @param  line: assert_param error line source number
 */
void assert_failed(uint8_t *file, uint32_t line)
{ 
  /* User can add his own implementation to report the file name and line number */
}
#endif /* USE_FULL_ASSERT */
MccsDaqReceiver Diagnostic Attributes
=====================================

This document details the available diagnostic attributes on the DAQ.

These metrics are placed at one of three steps in the DAQ:

1. Interface Diagnostics - These are measuring the data over the virtualised interface the DAQ pod has mounted. 
   This means it only sees data directed to it.
2. Ringbuffer Diagnostics - These measure the capacity and performance of the ringbuffer. 
   The producer captures data and writes it into the ring buffer, and the consumer pulls from it. 
   If the consumer is slower than the producer, the buffer will fill up. 
   Once the ring buffer is full, packets are dropped until there is space again.
3. Consumer Diagnostics - These measure the performance of the consumers pulling from the ringbuffer. 
   Typically these will show issues if the ringbuffer is filling up.


.. image:: diagnostics.png

Interface Diagnostics
---------------------

.. attribute:: dataRate

   **Type:** DevFloat

   **Unit:** Gb/s

   Data rate measured over the DAQ interface, independent of the DaqReceiver component.

   For the station beam, the expected data rate per Hz of bandwidth may be calculated as:

.. math::

   \underbrace{\frac{32}{27}}_{\text{Oversampling}}
   \times
   \underbrace{2}_{\text{Polarisations}}
   \times
   \underbrace{2}_{\text{Real/Imag}}
   \times
   \underbrace{\frac{8290}{8192}}_{\text{SPEAD overhead}}
   \approx 4.79 \ \text{(b/(s*Hz))}

which gives a data rate for maximum bandwidth of:

.. math::

   \frac{4.79\ \text{(b/(s*Hz))}
   \times
   300 \times 10^6\ \text{Hz}}
   {1024^3\ \text{(b/Gb)}}
   \approx 1.340\ \text{(Gb/s)}

.. attribute:: receiveRate

   **Type:** DevFloat

   **Unit:** packet/s

   Rate of packets received over the DAQ interface. This metric is independent of the DaqReceiver.

.. attribute:: dropRate

   **Type:** DevFloat

   **Unit:** packet/s 

   Rate at which packets are being dropped at the DAQ interface.
   Dropping may occur due to buffer overflows or network congestion.

Ringbuffer Diagnostics
----------------------

.. attribute:: RingbufferOccupancy

   **Type:** DevFloat

   **Unit:** % 

   Percentage of ringbuffer currently in use. When this approaches 100%, incoming packets are at risk of being dropped
   because the consumer is not processing data fast enough.

.. attribute:: LostPushes

   **Type:** DevLong 

   Total number of failed attempts to push data into the ringbuffer.
   This typically increases when the buffer is full or consumer lag is high.

.. attribute:: lostPushRate

   **Type:** DevFloat 

   **Unit:** packets/second

   Rate of failed pushes to the ringbuffer per second.

Consumer Diagnostics
--------------------

.. attribute:: nofSaturations

   **Type:** DevLong 

   Number of saturation events recorded during the most recent integration by the station beam consumer.

.. attribute:: nofPackets

   **Type:** DevLong

    Total number of packets processed during the last integration by the data consumer.

    1. For the station beam consumer this is dependent on the integration time, the higher the integation time
       the more packets we expect per integration.
    2. For the correlator data consumer, this at the moment should be 1835008/128 per TPM as each packet contains 128 samples, and nof samples is fixed to 1835008. 
       Note: there is some odd behaviour with this attribute at the beginning/end of a frequency sweep which is not yet understood.
    3. For the integrated channel data consumer (bandpasses), should be 32 packets per TPM sending data as each packet contains data for 8 antennas and 32 channels.

.. attribute:: relativeNofPacketsDiff

   **Type** DevFloat

   **Unit:** percentage  

    The amount the amount of packets received at the last consumer interation compared to what we expect given consumer configuration. E.g if DAQ is configured to
    receive a station beam for 384 channels, and to integrate 262144 samples, it expect to receive 384 * 262144/2048 packets per integration. (As there are 2048 samples
    per packet). The attribute will then alarm if, for example, the DAQ is falling behind and only managed to process half that many packets last integration.

    The expected nof packets calculation is different for each consumer.  

.. attribute:: nofSamples

   **Type:** DevLong

   Total number of data samples received in the last callback from the running consumer.

   For the correlator data consumer, this at the moment should be 1835008 as the correlator is fixed to this integration period.
   Note: there is some odd behaviour with this attribute at the beginning/end of a frequency sweep which is not yet understood.
    
.. attribute:: relativeNofSamplesDiff

   **Type** DevFloat

   **Unit:** percentage  

    The amound of samples received at the last consumer interation compared to what we expect given consumer configuration. E.g if DAQ is configured to integrate 262144
    station beam samples, it compares what it actually did with that and this attribute will alarm if the percentage difference is greater than configured limits.

.. attribute:: correlatorTimeTaken

   **Type:** DevFloat

   **Unit:** milliseconds (ms)  

   Time taken to complete the last correlation in xGPU, measured in milliseconds.
   A rising trend may indicate GPU contention or performance bottlenecks.

.. attribute:: correlatorTimeUtil

   **Type:** DevFloat

   **Unit:** percentage  

   Time taken to complete the last correlation in xGPU, compared to how long we have available, given current DAQ configuration.

   E.g For a correlation of 1835008 samples, the sampling time is 1835008/925925.925 seconds. This means the TPMs will spend about 2 seconds per channel.
   The consumer loads those samples into a buffer, then once the next channel arrives it moves to the next buffer. This means the consumer rotates through buffers
   at a rate dependent on how long we are sampling for. If the correlator takes longer than the time we are sampling for, eventually once we run out of buffers,
   the consumer will rotate back to buffers which have not yet been solved, and we drop channels from the frequency sweep.

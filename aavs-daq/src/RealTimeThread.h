//
// Created by lessju on 26/08/2015.
//

#ifndef _THREADCLASS_H
#define _THREADCLASS_H

#include <pthread.h>
#include <cstdio>
#include <cstdlib>


class RealTimeThread
{
    public:
        RealTimeThread() = default;

        virtual ~RealTimeThread() = default;

        // Returns true if the thread was successfully started, false if there was an error starting the thread
        bool startThread(bool reset_after_create=true)
        {
            pthread_attr_t attr{};
            sched_param param{};

            // Set thread with maximum priority
            pthread_attr_init(&attr);

            int ret = pthread_attr_setschedpolicy(&attr, SCHED_FIFO);
            if (ret != 0)
                perror("Couldn't set thread scheduling policy");

            // Give thread maximum priority
            param.sched_priority = sched_get_priority_max(SCHED_FIFO);

            // Set scheduling scope to system
            pthread_attr_setinheritsched(&attr, PTHREAD_EXPLICIT_SCHED);
            pthread_attr_setscope(&attr, PTHREAD_SCOPE_SYSTEM);

            // Set scheduling parameters
            ret = pthread_attr_setschedparam(&attr, &param);
            if (ret != 0)
                perror("Cannot set pthread scheduling policy");

            // Create thread
            ret = pthread_create(&_thread, &attr, threadEntryFunc, this);

            // Reset scheduling parameters for this thread
            if (reset_after_create) {
                param.sched_priority = 0;
                pthread_attr_setschedpolicy(&attr, 0);
            }

            return ret == 0;
        }

        // Set thread affinity
        int setThreadAffinity(unsigned int mask)
        {
            // Create CPU mask
            cpu_set_t cpuset{};
            CPU_ZERO(&cpuset);
            CPU_SET(mask, &cpuset);

            // Apply CPU set
            int ret = pthread_setaffinity_np(_thread, sizeof(cpu_set_t), &cpuset);
            if (ret != 0)
                return -1;

            return 0;
        }

        // Will not return until the internal thread has exited.
        void waitForThreadToExit()
        {
            (void) pthread_join(_thread, nullptr);
        }

        // Stop thread
        void stop()
        {
            this -> stop_thread = true;
            this -> waitForThreadToExit();
        }

    protected:
        // Implement this method in your subclass with the code you want your thread to run.
        virtual void threadEntry() = 0;
        volatile  bool stop_thread = false;

        // Set thread name (primarily for logging)
        static void setName(const char* name) {
            pthread_setname_np(pthread_self(), name);
        }

    private:
        static void *threadEntryFunc(void *This) { ((RealTimeThread *) This)->threadEntry(); return nullptr;}

        pthread_t _thread = 0;
};

#endif // _THREADCLASS_H

NielsenIQ Innovation Enablement
Homework

Introduction
We appreciate the effort of doing this exercise. If you have any trouble or challenge solving
this during the agreed time window, just let us know so we can find a solution.

Assignment
We’ve built an application that receives an image and a threshold and

● detects the objects in the image,

● counts those whose confidence score is above the given threshold, grouped by their
class (cat, cup, racket, ...) and

● returns the number of objects by class and the accumulated total.

The source code of this application can be shared via a zip folder or GitHub creating a fork
of this repository.

https://github.com/gsarwarllm/object-counter-vibe-coding.git

The assignment consists in performing the following tasks:

   1. Add a new service endpoint to receive the image and the desired threshold and
      return the list of predictions.
   2. Write a new adapter for ObjectCountRepo to persist data using a relational (MySQL
      or PostgreSQL) database.
   3. Review the rest of the source code and propose some improvements that you
      would make in the code, the setup instructions, the tests,...
   4. Implement at least one of the proposed improvements.
   5. If we want to use multiple models trained internally (not public), what would you
      change in the setup of the project?
   6. Choose one of the following
           a. Improve the testing by adding integration and e2e tests (or any other
               improvements you consider necessary)
           b. Support models for object detection using different deep learning
               frameworks. If the task seems too big, just lay out the main key points of the
               proposed solution.

Evaluation
Things that we evaluate and take into consideration about this test.

•   At least 3 of the exercises have been correctly solved.
•   The code is easy to understand following Clean code You can use these rules as a
    Reference)
•   The setup is automated and smoothly reproducible.
    o README.md is present and specifies how to set up the application.
    o Those instructions are enough to run the application in a local environment.
    o The instructions specify every task needed (download additional resources,
       run, test, admin scripts,...)
    o If 2 steps can be automated as one using a task manager (e.g. Makefile), this
       is preferred to write 2 commands in the README file.
•   Additional documentation is well written (precision, correctness,...)

Post-homework interview
A panel of two or three NielsenIQ associates will evaluate the candidate to ask for

•   Explaining his/her homework and the decisions made,
•   Give/receive feedback,
•   Discuss and reason about related topics during the conversation.

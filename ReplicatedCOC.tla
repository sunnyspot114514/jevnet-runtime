------------------------------ MODULE ReplicatedCOC ------------------------------
EXTENDS Naturals, FiniteSets

CONSTANT SafeProtocol

Nodes == {"A", "B", "C"}
Values == {"X", "Y"}
None == "None"
Ballots == 1..2
Partitions == {"FULL", "AB_C", "AC_B", "BC_A"}

Leader(b) == IF b = 1 THEN "A" ELSE "C"

Component(p, n) ==
    CASE p = "FULL" -> Nodes
      [] p = "AB_C" -> IF n \in {"A","B"} THEN {"A","B"} ELSE {"C"}
      [] p = "AC_B" -> IF n \in {"A","C"} THEN {"A","C"} ELSE {"B"}
      [] p = "BC_A" -> IF n \in {"B","C"} THEN {"B","C"} ELSE {"A"}

Reachable(p, a, b) == b \in Component(p, a)

Quorum(q) ==
    /\ q \subseteq Nodes
    /\ Cardinality(q) = 2

VARIABLES promised, acceptedBallot, acceptedValue,
          ballotValue, partition, chosen

vars == <<promised, acceptedBallot, acceptedValue,
          ballotValue, partition, chosen>>

TypeOK ==
    /\ promised \in [Nodes -> 0..2]
    /\ acceptedBallot \in [Nodes -> 0..2]
    /\ acceptedValue \in [Nodes -> (Values \cup {None})]
    /\ ballotValue \in [Ballots -> (Values \cup {None})]
    /\ partition \in Partitions
    /\ chosen \subseteq Values

Init ==
    /\ promised = [n \in Nodes |-> 0]
    /\ acceptedBallot = [n \in Nodes |-> 0]
    /\ acceptedValue = [n \in Nodes |-> None]
    /\ ballotValue = [b \in Ballots |-> None]
    /\ partition = "FULL"
    /\ chosen = {}

MaxAccepted(q) ==
    IF \E n \in q : acceptedBallot[n] = 2
    THEN 2
    ELSE IF \E n \in q : acceptedBallot[n] = 1
         THEN 1
         ELSE 0

InheritedValue(q) ==
    LET mb == MaxAccepted(q) IN
    IF mb = 0
    THEN None
    ELSE CHOOSE v \in Values :
            \E n \in q :
                /\ acceptedBallot[n] = mb
                /\ acceptedValue[n] = v

SelectedValue(q, candidate) ==
    IF SafeProtocol /\ MaxAccepted(q) > 0
    THEN InheritedValue(q)
    ELSE candidate

ChangePartition(p) ==
    /\ p \in Partitions
    /\ p # partition
    /\ partition' = p
    /\ UNCHANGED <<promised, acceptedBallot, acceptedValue, ballotValue, chosen>>

Prepare(b, candidate, q) ==
    /\ b \in Ballots
    /\ candidate \in Values
    /\ ballotValue[b] = None
    /\ Quorum(q)
    /\ Leader(b) \in q
    /\ q \subseteq Component(partition, Leader(b))
    /\ \A n \in q : promised[n] < b
    /\ promised' = [n \in Nodes |-> IF n \in q THEN b ELSE promised[n]]
    /\ ballotValue' = [ballotValue EXCEPT ![b] = SelectedValue(q, candidate)]
    /\ UNCHANGED <<acceptedBallot, acceptedValue, partition, chosen>>

Accept(b, n) ==
    /\ b \in Ballots
    /\ n \in Nodes
    /\ ballotValue[b] # None
    /\ Reachable(partition, Leader(b), n)
    /\ b >= promised[n]
    /\ ~ (acceptedBallot[n] = b /\ acceptedValue[n] = ballotValue[b])
    /\ LET newPromised ==
              [promised EXCEPT ![n] = b]
           newAcceptedBallot ==
              [acceptedBallot EXCEPT ![n] = b]
           newAcceptedValue ==
              [acceptedValue EXCEPT ![n] = ballotValue[b]]
           count ==
              Cardinality({m \in Nodes :
                  newAcceptedBallot[m] = b /\
                  newAcceptedValue[m] = ballotValue[b]})
       IN
       /\ promised' = newPromised
       /\ acceptedBallot' = newAcceptedBallot
       /\ acceptedValue' = newAcceptedValue
       /\ chosen' =
            IF count >= 2
            THEN chosen \cup {ballotValue[b]}
            ELSE chosen
    /\ UNCHANGED <<ballotValue, partition>>

Next ==
    \/ \E p \in Partitions : ChangePartition(p)
    \/ \E b \in Ballots, candidate \in Values, q \in SUBSET Nodes :
           Prepare(b, candidate, q)
    \/ \E b \in Ballots, n \in Nodes : Accept(b, n)

Safety == Cardinality(chosen) <= 1

Spec == Init /\ [][Next]_vars

=============================================================================

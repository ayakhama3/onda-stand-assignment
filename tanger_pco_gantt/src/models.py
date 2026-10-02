"""
Modèles de données — Système de Gantt de stationnement optimisé (PCO Tanger)

Utilise SQLite pour le prototype (aucune installation serveur requise).
Le schéma est directement transposable vers PostgreSQL (Neon) en production :
il suffit de changer l'URL de connexion dans database.py.
"""

from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Boolean,
    DateTime, ForeignKey
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class ParkingStand(Base):
    __tablename__ = "parking_stands"

    id = Column(Integer, primary_key=True)
    nom = Column(String, nullable=False)
    taille_max = Column(String, nullable=False)   # 'code_C' ou 'code_E'
    push_back_requis = Column(Boolean, default=False)
    latitude = Column(Float)
    longitude = Column(Float)

    assignments = relationship("StandAssignment", back_populates="stand")


class Gate(Base):
    __tablename__ = "gates"

    id = Column(Integer, primary_key=True)
    nom = Column(String, nullable=False)
    stand_id_proche = Column(Integer, ForeignKey("parking_stands.id"))


class CheckinCounter(Base):
    __tablename__ = "checkin_counters"

    id = Column(Integer, primary_key=True)
    numero = Column(String, nullable=False)
    zone = Column(String)


class Flight(Base):
    __tablename__ = "flights"

    id = Column(Integer, primary_key=True)
    numero_vol = Column(String, nullable=False)
    icao24 = Column(String)                      # identifiant transpondeur (lien OpenSky)
    immatriculation = Column(String)
    type_appareil = Column(String, nullable=False)
    taille_appareil = Column(String, nullable=False)  # 'code_C' ou 'code_E'
    compagnie = Column(String)
    saison_iata = Column(String)                  # 'ete' | 'hiver'
    date_vol = Column(DateTime)
    heure_prevue_arrivee = Column(DateTime, nullable=False)
    heure_prevue_depart = Column(DateTime, nullable=False)
    statut = Column(String, default="prevu")      # prevu | retarde | annule | atterri
    gate_id = Column(Integer, ForeignKey("gates.id"))
    counter_1_id = Column(Integer, ForeignKey("checkin_counters.id"))
    counter_2_id = Column(Integer, ForeignKey("checkin_counters.id"))

    assignment = relationship("StandAssignment", back_populates="flight", uselist=False)


class StandAssignment(Base):
    __tablename__ = "stand_assignments"

    id = Column(Integer, primary_key=True)
    flight_id = Column(Integer, ForeignKey("flights.id"))
    stand_id = Column(Integer, ForeignKey("parking_stands.id"))
    date_calcul = Column(DateTime)
    statut_validation = Column(String, default="proposee")  # proposee | validee | modifiee
    agent_id = Column(Integer, nullable=True)

    flight = relationship("Flight", back_populates="assignment")
    stand = relationship("ParkingStand", back_populates="assignments")


class RotationChange(Base):
    __tablename__ = "rotation_changes"

    id = Column(Integer, primary_key=True)
    flight_id = Column(Integer, ForeignKey("flights.id"))
    date_heure_detection = Column(DateTime)
    type_changement = Column(String)   # retard | annulation | poste_modifie
    ancienne_valeur = Column(String)
    nouvelle_valeur = Column(String)
    statut_traite = Column(Boolean, default=False)


def get_engine(db_path="sqlite:///data/pco_gantt.db"):
    return create_engine(db_path)


def init_db(engine):
    Base.metadata.create_all(engine)
